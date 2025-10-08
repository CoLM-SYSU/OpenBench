import os
import re
import shutil
import sys
import warnings
import logging
import gc

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from joblib import Parallel, delayed

# Import parallel engine
try:
    from openbench.util.Mod_ParallelEngine import (
    get_parallel_engine,
    parallel_map,
    parallel_decorator,
    ParallelEngine
)
    _HAS_PARALLEL_ENGINE = True
except ImportError:
    _HAS_PARALLEL_ENGINE = False
    ParallelEngine = None
    def get_parallel_engine(*args, **kwargs):
        return None
    def parallel_map(*args, **kwargs):
        # Fallback to sequential processing
        func = args[0]
        items = args[1]
        return [func(item) for item in items]

# Import CacheSystem - CacheSystem is mandatory for evaluation engine
try:
    from openbench.data.Mod_CacheSystem import cached, get_cache_manager
    _HAS_CACHE = True
except ImportError:
    raise RuntimeError(
        "CacheSystem is required for evaluation engine (务必使用CacheSystem). "
        "Please ensure openbench.data.Mod_CacheSystem is available."
    )

# Check the platform
from ..metrics.Mod_Metrics import metrics
from ..scoring.Mod_Scores import scores
from openbench.visualization import *
from openbench.util.Mod_Converttype import Convert_Type

# Import climatology processor
try:
    from openbench.data.Mod_Climatology import ClimatologyProcessor, process_climatology_evaluation
    _HAS_CLIMATOLOGY = True
except ImportError:
    _HAS_CLIMATOLOGY = False
    ClimatologyProcessor = None
    def process_climatology_evaluation(*args, **kwargs):
        return args[0], args[1], args[2]

# Import modular evaluation engine
try:
    from .Mod_EvaluationEngine import (
    ModularEvaluationEngine, 
    GridEvaluationEngine, 
    StationEvaluationEngine,
    create_evaluation_engine,
    evaluate_datasets
)
    _HAS_MODULAR_ENGINE = True
except ImportError:
    _HAS_MODULAR_ENGINE = False
    ModularEvaluationEngine = object
    GridEvaluationEngine = object
    StationEvaluationEngine = object
    def create_evaluation_engine(*args, **kwargs):
        return None
    def evaluate_datasets(*args, **kwargs):
        return {}

# Import output manager
try:
    from openbench.util.Mod_OutputManager import (
    ModularOutputManager,
    create_output_manager,
    save_evaluation_results
)
    _HAS_OUTPUT_MANAGER = True
except ImportError:
    _HAS_OUTPUT_MANAGER = False
    ModularOutputManager = object
    def create_output_manager(*args, **kwargs):
        return None
    def save_evaluation_results(*args, **kwargs):
        return ""

# Configure logging
logging.getLogger('xarray').setLevel(logging.WARNING)  # Suppress INFO messages from xarray
warnings.filterwarnings('ignore', category=RuntimeWarning)  # Suppress numpy runtime warnings
logging.getLogger('dask').setLevel(logging.WARNING)  # Suppress INFO messages from dask
class Evaluation_grid(metrics, scores):
    def _calculate_metric(self, s, o, metric):
        """Helper method for parallel metric calculation."""
        try:
            if hasattr(self, metric):
                self.process_metric(metric, s, o)
                return metric
            else:
                logging.error(f'No such metric: {metric}')
                return None
        except Exception as e:
            logging.error(f'Error calculating metric {metric}: {e}')
            return None
    def __init__(self, info, fig_nml):
        self.name = 'Evaluation_grid'
        self.version = '0.1'
        self.release = '0.1'
        self.date = 'Mar 2023'
        self.author = "Zhongwang Wei / zhongwang007@gmail.com"
        self.__dict__.update(info)
        self.fig_nml = fig_nml
        os.makedirs(os.path.join(self.casedir, 'output'), exist_ok=True)

        # Initialize modular evaluation engine if available
        if _HAS_MODULAR_ENGINE:
            self.modular_engine = create_evaluation_engine('grid')
            logging.debug("Modular grid evaluation engine initialized")
        else:
            self.modular_engine = None
        
        # Initialize output manager if available
        if _HAS_OUTPUT_MANAGER:
            self.output_manager = create_output_manager(
                os.path.join(self.casedir, 'output')
            )
            logging.debug("Output manager initialized")
        else:
            self.output_manager = None

        logging.info(" ")
        logging.info("╔═══════════════════════════════════════════════════════════════╗")
        logging.info("║                Evaluation processes starting!                 ║")
        logging.info("╚═══════════════════════════════════════════════════════════════╝")
        logging.info(" ")

    @cached(key_prefix="eval_metric", ttl=1800)
    def process_metric(self, metric, s, o, vkey=''):
        try:
            pb = getattr(self, metric)(s, o)
            pb = pb.squeeze()
            pb_da = xr.DataArray(pb, coords=[o.lat, o.lon], dims=['lat', 'lon'], name=metric)
            
            # Use output manager if available, otherwise fallback to original method
            if self.output_manager:
                filename = f'{self.item}_ref_{self.ref_source}_sim_{self.sim_source}_{metric}{vkey}'
                metadata = {
                    'metric': metric,
                    'item': self.item,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source,
                    'variable_key': vkey
                }
                output_path = self.output_manager.save_data(
                    pb_da, 'metrics', filename, 'netcdf', metadata
                )
            else:
                # Original method
                output_path = os.path.join(self.casedir, 'output', 'metrics', 
                                         f'{self.item}_ref_{self.ref_source}_sim_{self.sim_source}_{metric}{vkey}.nc')
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                pb_da.to_netcdf(output_path)
                logging.info(f"Saved metric {metric} to {output_path}")
        finally:
            gc.collect()  # Clean up memory after processing each metric

    def process_score(self, score, s, o, vkey=''):
        try:
            pb = getattr(self, score)(s, o)
            pb = pb.squeeze()
            pb_da = xr.DataArray(pb, coords=[o.lat, o.lon], dims=['lat', 'lon'], name=score)
            
            # Use output manager if available, otherwise fallback to original method
            if self.output_manager:
                filename = f'{self.item}_ref_{self.ref_source}_sim_{self.sim_source}_{score}{vkey}'
                metadata = {
                    'score': score,
                    'item': self.item,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source,
                    'variable_key': vkey
                }
                output_path = self.output_manager.save_data(
                    pb_da, 'scores', filename, 'netcdf', metadata
                )
            else:
                # Original method
                output_path = os.path.join(self.casedir, 'output', 'scores', 
                                         f'{self.item}_ref_{self.ref_source}_sim_{self.sim_source}_{score}{vkey}.nc')
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                pb_da.to_netcdf(output_path)
                logging.info(f"Saved score {score} to {output_path}")
        finally:
            gc.collect()  # Clean up memory after processing each score

    @cached(key_prefix="grid_eval", ttl=1800)
    def make_Evaluation(self, **kwargs):
        ref_ds = None
        sim_ds = None
        try:
            ref_path = os.path.join(self.casedir, 'output', 'data',
                                  f'{self.item}_ref_{self.ref_source}_{self.ref_varname}.nc')
            sim_path = os.path.join(self.casedir, 'output', 'data',
                                  f'{self.item}_sim_{self.sim_source}_{self.sim_varname}.nc')

            # Open datasets and keep references for proper cleanup
            ref_ds = xr.open_dataset(ref_path)
            sim_ds = xr.open_dataset(sim_path)
            o = ref_ds[f'{self.ref_varname}']
            s = sim_ds[f'{self.sim_varname}']
            o = Convert_Type.convert_nc(o)
            s = Convert_Type.convert_nc(s)

            # Process climatology if applicable
            if _HAS_CLIMATOLOGY:
                original_metrics = self.metrics.copy() if hasattr(self.metrics, 'copy') else list(self.metrics)
                original_scores = self.scores.copy() if hasattr(self.scores, 'copy') else list(self.scores)

                # Combine metrics and scores for filtering
                all_evaluations = list(self.metrics) + list(self.scores)

                # Get data_groupby information from instance attributes
                ref_data_groupby = getattr(self, 'ref_data_groupby', None)
                sim_data_groupby = getattr(self, 'sim_data_groupby', None)

                o_clim, s_clim, supported_evaluations = process_climatology_evaluation(
                    ref_ds, sim_ds, all_evaluations,
                    ref_data_groupby=ref_data_groupby,
                    sim_data_groupby=sim_data_groupby
                )

                if o_clim is not None and s_clim is not None:
                    # Climatology evaluation mode
                    logging.info("=" * 80)
                    logging.info("CLIMATOLOGY EVALUATION MODE DETECTED")
                    logging.info("=" * 80)

                    o = o_clim[f'{self.ref_varname}']
                    s = s_clim[f'{self.sim_varname}']
                    o = Convert_Type.convert_nc(o)
                    s = Convert_Type.convert_nc(s)

                    # Update metrics and scores to only supported ones
                    self.metrics = [m for m in self.metrics if m in supported_evaluations]
                    self.scores = [sc for sc in self.scores if sc in supported_evaluations]

                    if len(self.metrics) < len(original_metrics):
                        skipped_metrics = set(original_metrics) - set(self.metrics)
                        logging.info(f"Skipped metrics for climatology: {skipped_metrics}")

                    if len(self.scores) < len(original_scores):
                        skipped_scores = set(original_scores) - set(self.scores)
                        logging.info(f"Skipped scores for climatology: {skipped_scores}")

                    logging.info("=" * 80)
                else:
                    # Regular time series evaluation
                    s['time'] = o['time']
            else:
                s['time'] = o['time']

            if self.item == 'Terrestrial_Water_Storage_Change':
                logging.info("Processing Terrestrial Water Storage Change...")
                # Calculate time difference while preserving coordinates
                s_values = s.values
                s_values[1:,:,:] = s_values[1:,:,:] - s_values[:-1,:,:]
                s_values[0,:,:] = np.nan
                s.values = s_values
                # Save s to original file
                s.to_netcdf(sim_path)

            mask1 = np.isnan(s) | np.isnan(o)
            s.values[mask1] = np.nan
            o.values[mask1] = np.nan
            logging.info("=" * 80)

            # Parallel processing of metrics if available and beneficial
            if _HAS_PARALLEL_ENGINE and len(self.metrics) > 3:
                logging.info("Processing metrics in parallel")
                from functools import partial
                metric_func = partial(self._calculate_metric, s, o)
                metric_results = parallel_map(
                    metric_func,
                    self.metrics,
                    task_name="Calculating metrics",
                    show_progress=False,
                    max_workers=min(4, len(self.metrics))
                )
                # Process results
                for metric, result in zip(self.metrics, metric_results):
                    if result is not None:
                        logging.info(f'Calculated metric: {metric}')
            else:
                # Sequential processing
                for metric in self.metrics:
                    if hasattr(self, metric):
                        logging.info(f'Calculating metric: {metric}')
                        self.process_metric(metric, s, o)
                    else:
                        logging.error(f'No such metric: {metric}')
                        sys.exit(1)

            # Process scores (usually fewer, so sequential is fine)
            for score in self.scores:
                if hasattr(self, score):
                    logging.info(f'Calculating score: {score}')
                    self.process_score(score, s, o)
                else:
                    logging.error(f'No such score: {score}')
                    sys.exit(1)

            logging.info("=" * 80)
            make_plot_index_grid(self)
        finally:
            # Close datasets to free memory and file handles
            if ref_ds is not None:
                ref_ds.close()
            if sim_ds is not None:
                sim_ds.close()
            gc.collect()  # Final cleanup

class Evaluation_stn(metrics, scores):
    def __init__(self, info, fig_nml):
        self.name = 'Evaluation_point'
        self.version = '0.1'
        self.release = '0.1'
        self.date = 'Mar 2023'
        self.author = "Zhongwang Wei / zhongwang007@gmail.com"
        self.fig_nml = fig_nml
        self.__dict__.update(info)
        if isinstance(self.sim_varname, str): self.sim_varname = [self.sim_varname]
        if isinstance(self.ref_varname, str): self.ref_varname = [self.ref_varname]

        # Initialize modular evaluation engine if available
        if _HAS_MODULAR_ENGINE:
            self.modular_engine = create_evaluation_engine('station')
            logging.debug("Modular station evaluation engine initialized")
        else:
            self.modular_engine = None
        
        # Initialize output manager if available
        if _HAS_OUTPUT_MANAGER:
            self.output_manager = create_output_manager(
                os.path.join(self.casedir, 'output')
            )
            logging.debug("Output manager initialized")
        else:
            self.output_manager = None

        logging.info('Evaluation processes starting!')
        logging.info("=======================================")
        logging.info(" ")
        logging.info(" ")

    def make_evaluation(self):
        try:
            # read station information
            stnlist = os.path.join(self.casedir, "stn_list.txt")
            station_list = Convert_Type.convert_Frame(pd.read_csv(stnlist, header=0))

            # loop the keys in self.variables to get the metric output
            for metric in self.metrics:
                station_list[f'{metric}'] = [-9999.0] * len(station_list['ID'])
            for score in self.scores:
                station_list[f'{score}'] = [-9999.0] * len(station_list['ID'])
            
            for iik in range(len(station_list['ID'])):
                sim_ds = None
                ref_ds = None
                try:
                    sim_path = os.path.join(self.casedir, "output", "data", f"stn_{self.ref_source}_{self.sim_source}",
                                          f"sim_{station_list['ID'][iik]}_{station_list['use_syear'][iik]}_{station_list['use_eyear'][iik]}.nc")
                    ref_path = os.path.join(self.casedir, "output", "data", f"stn_{self.ref_source}_{self.sim_source}",
                                          f"ref_{station_list['ID'][iik]}_{station_list['use_syear'][iik]}_{station_list['use_eyear'][iik]}.nc")

                    # Open datasets and keep references for proper cleanup
                    sim_ds = xr.open_dataset(sim_path)
                    ref_ds = xr.open_dataset(ref_path)
                    s = sim_ds[self.sim_varname]
                    o = ref_ds[self.ref_varname]

                    # Process climatology if applicable
                    current_metrics = self.metrics
                    current_scores = self.scores

                    if _HAS_CLIMATOLOGY:
                        all_evaluations = list(self.metrics) + list(self.scores)

                        # Get data_groupby information from instance attributes
                        ref_data_groupby = getattr(self, 'ref_data_groupby', None)
                        sim_data_groupby = getattr(self, 'sim_data_groupby', None)

                        o_clim, s_clim, supported_evaluations = process_climatology_evaluation(
                            ref_ds, sim_ds, all_evaluations,
                            ref_data_groupby=ref_data_groupby,
                            sim_data_groupby=sim_data_groupby
                        )

                        if o_clim is not None and s_clim is not None:
                            # Climatology evaluation for this station
                            o = o_clim[self.ref_varname]
                            s = s_clim[self.sim_varname]

                            # Filter to supported evaluations
                            current_metrics = [m for m in self.metrics if m in supported_evaluations]
                            current_scores = [sc for sc in self.scores if sc in supported_evaluations]
                        else:
                            s['time'] = o['time']
                    else:
                        s['time'] = o['time']

                    mask1 = np.isnan(s) | np.isnan(o)
                    s.values[mask1] = np.nan
                    o.values[mask1] = np.nan

                    for metric in current_metrics:
                        if hasattr(self, metric):
                            pb = getattr(self, metric)(s, o)
                            station_list.loc[iik, f'{metric}'] = pb.values
                        else:
                            logging.error('No such metric')
                            sys.exit(1)

                    for score in current_scores:
                        if hasattr(self, score):
                            pb = getattr(self, score)(s, o)
                            station_list.loc[iik, f'{score}'] = pb.values
                        else:
                            logging.error('No such score')
                            sys.exit(1)
                finally:
                    # Close datasets to free memory and file handles
                    if sim_ds is not None:
                        sim_ds.close()
                    if ref_ds is not None:
                        ref_ds.close()
                    gc.collect()  # Clean up memory after each station

            logging.info('Comparison dataset prepared!')
            logging.info("=======================================")
            
            station_list = Convert_Type.convert_Frame(station_list)
            
            # Save metrics and scores using output manager if available
            if self.output_manager:
                # Save metrics
                metrics_filename = f'{self.ref_varname}_{self.sim_varname}_metrics'
                metrics_metadata = {
                    'type': 'station_metrics',
                    'ref_varname': self.ref_varname,
                    'sim_varname': self.sim_varname,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source
                }
                self.output_manager.save_data(
                    station_list, 'metrics', metrics_filename, 'csv', 
                    metrics_metadata, [f'stn_{self.ref_source}_{self.sim_source}']
                )
                
                # Save scores
                scores_filename = f'{self.ref_varname}_{self.sim_varname}_scores'
                scores_metadata = {
                    'type': 'station_scores',
                    'ref_varname': self.ref_varname,
                    'sim_varname': self.sim_varname,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source
                }
                self.output_manager.save_data(
                    station_list, 'scores', scores_filename, 'csv', 
                    scores_metadata, [f'stn_{self.ref_source}_{self.sim_source}']
                )
            else:
                # Original method
                # Save metrics
                metrics_dir = os.path.join(self.casedir, 'output', 'metrics', f'stn_{self.ref_source}_{self.sim_source}')
                os.makedirs(metrics_dir, exist_ok=True)
                metrics_path = os.path.join(metrics_dir, f'{self.ref_varname}_{self.sim_varname}_metrics.csv')
                logging.info(f"Saving metrics to {metrics_path}")
                station_list.to_csv(metrics_path, index=False)
                
                # Save scores
                scores_dir = os.path.join(self.casedir, 'output', 'scores', f'stn_{self.ref_source}_{self.sim_source}')
                os.makedirs(scores_dir, exist_ok=True)
                scores_path = os.path.join(scores_dir, f'{self.ref_varname}_{self.sim_varname}_scores.csv')
                station_list.to_csv(scores_path, index=False)
        finally:
            gc.collect()  # Final cleanup

    def make_evaluation_parallel(self, station_list, iik):
        sim_ds = None
        ref_ds = None
        try:
            sim_path = os.path.join(self.casedir, "output", "data", f"stn_{self.ref_source}_{self.sim_source}",
                                  f"{self.item}_sim_{station_list['ID'][iik]}_{station_list['use_syear'][iik]}_{station_list['use_eyear'][iik]}.nc")
            ref_path = os.path.join(self.casedir, "output", "data", f"stn_{self.ref_source}_{self.sim_source}",
                                  f"{self.item}_ref_{station_list['ID'][iik]}_{station_list['use_syear'][iik]}_{station_list['use_eyear'][iik]}.nc")

            # Open datasets and keep references for proper cleanup
            sim_ds = xr.open_dataset(sim_path)
            ref_ds = xr.open_dataset(ref_path)
            s = sim_ds[self.sim_varname].to_array().squeeze()
            o = ref_ds[self.ref_varname].to_array().squeeze()
            o = Convert_Type.convert_nc(o)
            s = Convert_Type.convert_nc(s)

            s['time'] = o['time']
            mask1 = np.isnan(s) | np.isnan(o)
            s.values[mask1] = np.nan
            o.values[mask1] = np.nan

            row = {}
            # for based plot
            try:
                row['KGESS'] = self.KGESS(s, o).values
            except:
                row['KGESS'] = -9999.0
            try:
                row['RMSE'] = self.rmse(s, o).values
            except:
                row['RMSE'] = -9999.0
            try:
                row['correlation'] = self.correlation(s, o).values
            except:
                row['correlation'] = -9999.0

            for metric in self.metrics:
                if hasattr(self, metric):
                    pb = getattr(self, metric)(s, o)
                    if pb.values is not None:
                        row[f'{metric}'] = pb.values
                    else:
                        row[f'{metric}'] = -9999.0
                        if 'ref_lat' in station_list:
                            lat_lon = [station_list['ref_lat'][iik], station_list['ref_lon'][iik]]
                        else:
                            lat_lon = [station_list['sim_lat'][iik], station_list['sim_lon'][iik]]
                        plot_stn(self, s.squeeze(), o.squeeze(), station_list['ID'][iik], self.ref_varname,
                                      float(station_list['RMSE'][iik]), float(station_list['KGE'][iik]),
                                      float(station_list['correlation'][iik]), lat_lon)
                else:
                    logging.error(f'No such metric: {metric}')
                    sys.exit(1)

            for score in self.scores:
                if hasattr(self, score):
                    pb2 = getattr(self, score)(s, o)
                    if pb2.values is not None:
                        row[f'{score}'] = pb2.values
                    else:
                        row[f'{score}'] = -9999.0
                else:
                    logging.error('No such score')
                    sys.exit(1)

            if 'ref_lat' in station_list:
                lat_lon = [station_list['ref_lat'][iik], station_list['ref_lon'][iik]]
            else:
                lat_lon = [station_list['sim_lat'][iik], station_list['sim_lon'][iik]]
            plot_stn(self, s, o, station_list['ID'][iik], self.ref_varname, float(row['RMSE']), float(row['KGESS']),
                          float(row['correlation']), lat_lon)
            return row
        finally:
            # Close datasets to free memory and file handles
            if sim_ds is not None:
                sim_ds.close()
            if ref_ds is not None:
                ref_ds.close()
            gc.collect()  # Clean up memory after processing each station

    @cached(key_prefix="station_eval", ttl=1800)
    def make_evaluation_P(self):
        try:
            stnlist = os.path.join(self.casedir, "stn_list.txt")
            station_list = Convert_Type.convert_Frame(pd.read_csv(stnlist, header=0))
            
            # Use enhanced parallel engine if available
            if _HAS_PARALLEL_ENGINE:
                logging.info("Using enhanced parallel engine for station evaluation")
                
                # Create partial function with station_list
                from functools import partial
                eval_func = partial(self.make_evaluation_parallel, station_list)
                
                # Process stations in parallel
                results = parallel_map(
                    eval_func,
                    list(range(len(station_list['ID']))),
                    task_name="Evaluating stations",
                    show_progress=True
                )
            else:
                # Fallback to joblib
                results = Parallel(n_jobs=-1)(
                    delayed(self.make_evaluation_parallel)(station_list, iik) for iik in range(len(station_list['ID'])))
            
            station_list = pd.concat([station_list, pd.DataFrame(results)], axis=1)

            logging.info('Evaluation finished')
            logging.info("=======================================")

            station_list = Convert_Type.convert_Frame(station_list)
            
            # Save metrics and scores using output manager if available
            if self.output_manager:
                # Save scores
                scores_filename = f'{self.item}_stn_{self.ref_source}_{self.sim_source}_evaluations'
                scores_metadata = {
                    'type': 'station_evaluations_scores',
                    'item': self.item,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source
                }
                self.output_manager.save_data(
                    station_list, 'scores', scores_filename, 'csv', scores_metadata
                )
                
                # Save metrics
                metrics_filename = f'{self.item}_stn_{self.ref_source}_{self.sim_source}_evaluations'
                metrics_metadata = {
                    'type': 'station_evaluations_metrics',
                    'item': self.item,
                    'ref_source': self.ref_source,
                    'sim_source': self.sim_source
                }
                self.output_manager.save_data(
                    station_list, 'metrics', metrics_filename, 'csv', metrics_metadata
                )
            else:
                # Original method
                # Save scores
                scores_path = os.path.join(self.casedir, 'output', 'scores',
                                         f'{self.item}_stn_{self.ref_source}_{self.sim_source}_evaluations.csv')
                logging.info(f"Saving scores to {scores_path}")
                os.makedirs(os.path.dirname(scores_path), exist_ok=True)
                station_list.to_csv(scores_path, index=False)
                
                # Save metrics
                metrics_path = os.path.join(self.casedir, 'output', 'metrics',
                                          f'{self.item}_stn_{self.ref_source}_{self.sim_source}_evaluations.csv')
                logging.info(f"Saving metrics to {metrics_path}")
                os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
                station_list.to_csv(metrics_path, index=False)
            
            make_plot_index_stn(self)

        finally:
            gc.collect()  # Final cleanup

