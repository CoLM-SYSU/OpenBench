import os
import re
import shutil
import sys
import warnings
import logging
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr
from joblib import Parallel, delayed

# Check the platform
from ..metrics.Mod_Metrics import metrics
from ..scoring.Mod_Scores import scores
from openbench.util.Mod_Converttype import Convert_Type
from openbench.visualization import *


class CZ_groupby(metrics, scores):
    def __init__(self, main_nml, scores, metrics):
        self.name = 'StatisticsDataHandler'
        self.version = '0.3'
        self.release = '0.3'
        self._station_warning_shown = False  # Track if station data warning has been shown
        self.date = 'June 2024'
        self.author = "Zhongwang Wei"
        self.main_nml = main_nml
        self.general_config = self.main_nml['general']
        # update self based on self.general_config
        self.__dict__.update(self.general_config)
        # Extract remapping information from main namelist
        self.compare_grid_res = self.main_nml['general']['compare_grid_res']
        self.compare_tim_res = self.main_nml['general'].get('compare_tim_res', '1').lower()
        self.casedir = os.path.join(self.main_nml['general']['basedir'], self.main_nml['general']['basename'])
        # Set default weight method to 'none'
        self.weight = self.main_nml['general'].get('weight', 'none')
        # this should be done in read_namelist
        # adjust the time frequency
        match = re.match(r'(\d*)\s*([a-zA-Z]+)', self.compare_tim_res)
        if not match:
            logging.error(f"Invalid time resolution format. Use '3month', '6hr', etc.")
            raise ValueError("Invalid time resolution format. Use '3month', '6hr', etc.")
        value, unit = match.groups()
        if not value:
            value = 1
        else:
            value = int(value)  # Convert the numerical value to an integer
        self.metrics = metrics
        self.scores = scores

    def scenarios_CZ_groupby_comparison(self, casedir, sim_nml, ref_nml, evaluation_items, scores, metrics, option):
        def _CZ_class_remap_cdo(self):
            """
            Compare the Climate zone class of the model output data and the reference data
            """
            from openbench.data.regrid import regridder_cdo

            # creat a text file, record the grid information
            nx = int(360. / self.compare_grid_res)
            ny = int(180. / self.compare_grid_res)
            grid_info = f'{self.casedir}/output/metrics/CZ_groupby/CZ_info.txt'

            with open(grid_info, 'w') as f:
                f.write(f"gridtype = lonlat\n")
                f.write(f"xsize    =  {nx} \n")
                f.write(f"ysize    =  {ny}\n")
                f.write(f"xfirst   =  {self.min_lon + self.compare_grid_res / 2}\n")
                f.write(f"xinc     =  {self.compare_grid_res}\n")
                f.write(f"yfirst   =  {self.min_lat + self.compare_grid_res / 2}\n")
                f.write(f"yinc     =  {self.compare_grid_res}\n")
                f.close()
            self.target_grid = grid_info
            CZtype_orig = './dataset/Climate_zone.nc'
            CZtype_remap = f'{self.casedir}/output/metrics/CZ_groupby/CZ_remap.nc'
            regridder_cdo.largest_area_fraction_remap_cdo(self, CZtype_orig, CZtype_remap, self.target_grid)
            self.CZ_dir = CZtype_remap

        def _CZ_class_remap(self):
            """
            Compare the Climate zone class of the model output data and the reference data using xarray
            """
            from openbench.data.regrid import Grid, create_regridding_dataset, Regridder
            ds = xr.open_dataset("./dataset/Climate_zone.nc", chunks={"lat": 2000, "lon": 2000})
            ds = ds["climate_zone"]
            ds = ds.sortby(["lat", "lon"])
            # ds = ds.rename({"lat": "latitude", "lon": "longitude"})
            new_grid = Grid(
                north=self.max_lat - self.compare_grid_res / 2,
                south=self.min_lat + self.compare_grid_res / 2,
                west=self.min_lon + self.compare_grid_res / 2,
                east=self.max_lon - self.compare_grid_res / 2,
                resolution_lat=self.compare_grid_res,
                resolution_lon=self.compare_grid_res,
            )
            target_dataset = create_regridding_dataset(new_grid)
            ds_regrid = ds.astype(int).regrid.most_common(target_dataset, values=np.arange(1,30))
            CZtype_remap = f'{self.casedir}/output/metrics/CZ_groupby/CZ_remap.nc'
            ds_regrid.to_netcdf(CZtype_remap)
            self.CZ_dir = CZtype_remap

        def _scenarios_CZ_groupby(basedir, scores, metrics, sim_nml, ref_nml, evaluation_items):
            """
            Compare the Climate zone class of the model output data and the reference data
            """
            CZtype = xr.open_dataset(self.CZ_dir)['climate_zone']
            # convert CZ type to int
            CZtype = CZtype.astype(int)
            CZ_class_names = {
                1: "Af",
                2: "Am",
                3: "Aw",
                4: "BWh",
                5: "BWk",
                6: "BSh",
                7: "BSk",
                8: "Csa",
                9: "Csb",
                10: "Csc",
                11: "Cwa",
                12: "Cwb",
                13: "Cwc",
                14: "Cfa",
                15: "Cfb",
                16: "Cfc",
                17: "Dsa",
                18: "Dsb",
                19: "Dsc",
                20: "Dsd",
                21: "Dwa",
                22: "Dwb",
                23: "Dwc",
                24: "Dwd",
                25: "Dfa",
                26: "Dfb",
                27: "Dfc",
                28: "Dfd",
                29: "ET",
                30: "EF"
            }

            # read the simulation source and reference source
            for evaluation_item in evaluation_items:
                logging.info(f"now processing the evaluation item: {evaluation_item}")
                sim_sources = sim_nml['general'][f'{evaluation_item}_sim_source']
                ref_sources = ref_nml['general'][f'{evaluation_item}_ref_source']
                # if the sim_sources and ref_sources are not list, then convert them to list
                if isinstance(sim_sources, str): sim_sources = [sim_sources]
                if isinstance(ref_sources, str): ref_sources = [ref_sources]
                for ref_source in ref_sources:
                    for sim_source in sim_sources:
                        ref_data_type = ref_nml[f'{evaluation_item}'][f'{ref_source}_data_type']
                        sim_data_type = sim_nml[f'{evaluation_item}'][f'{sim_source}_data_type']
                        ref_varname = ref_nml[f'{evaluation_item}'][f'{ref_source}_varname']
                        sim_varname = sim_nml[f'{evaluation_item}'][f'{sim_source}_varname']
                        if ref_data_type == 'stn' or sim_data_type == 'stn':
                            if not self._station_warning_shown:
                                logging.warning(f"warning: station data is not supported for Climate zone class comparison")
                                self._station_warning_shown = True
                            continue  # Skip processing for station data
                        else:
                            dir_path = os.path.join(f'{basedir}', 'output', 'metrics', 'CZ_groupby',
                                                    f'{sim_source}___{ref_source}')
                            if not os.path.exists(dir_path):
                                os.makedirs(dir_path)

                            if len(self.metrics) > 0:
                                output_file_path = os.path.join(dir_path,
                                                                f'{evaluation_item}_{sim_source}___{ref_source}_metrics.txt')
                                with open(output_file_path, "w") as output_file:
                                    # Print the table header with an additional column for the overall median
                                    output_file.write("ID\t")
                                    for i in range(1, 31):
                                        output_file.write(f"{i}\t")
                                    output_file.write("All\n")  # Move "All" to the first line
                                    output_file.write("FullName\t")
                                    for CZ_class_name in CZ_class_names.values():
                                        output_file.write(f"{CZ_class_name}\t")
                                    output_file.write("Overall\n")  # Write "Overall" on the second line

                                    # Calculate and print median values

                                    for metric in self.metrics:
                                        ds = xr.open_dataset(
                                            f'{self.casedir}/output/metrics/{evaluation_item}_ref_{ref_source}_sim_{sim_source}_{metric}.nc')
                                        ds = Convert_Type.convert_nc(ds)
                                        output_file.write(f"{metric}\t")

                                        # Calculate and write the overall median first
                                        ds = ds.where(np.isfinite(ds), np.nan)
                                        q_value = ds[metric].quantile([0.05, 0.95], dim=['lat', 'lon'], skipna=True)
                                        ds = ds.where((ds >= q_value[0]) & (ds <= q_value[1]), np.nan)

                                        overall_median = ds[metric].median(skipna=True).values
                                        overall_median_str = f"{overall_median:.3f}" if not np.isnan(overall_median) else "N/A"

                                        for i in range(1, 31):
                                            ds1 = ds.where(CZtype == i)
                                            CZ_class_name = CZ_class_names.get(i, f"CZ_{i}")
                                            ds1.to_netcdf(
                                                f"{self.casedir}/output/metrics/CZ_groupby/{sim_source}___{ref_source}/{evaluation_item}_ref_{ref_source}_sim_{sim_source}_{metric}_CZ_{CZ_class_name}.nc")
                                            median_value = ds1[metric].median(skipna=True).values
                                            median_value_str = f"{median_value:.3f}" if not np.isnan(median_value) else "N/A"
                                            output_file.write(f"{median_value_str}\t")
                                        output_file.write(f"{overall_median_str}\t")  # Write overall median
                                        output_file.write("\n")

                                selected_metrics = self.metrics
                                # selected_metrics = list(selected_metrics)
                                option['path'] = f"{self.casedir}/output/metrics/CZ_groupby/{sim_source}___{ref_source}/"
                                option['item'] = [evaluation_item, sim_source, ref_source]
                                option['groupby'] = 'CZ_groupby'
                                make_CZ_based_heat_map(output_file_path, selected_metrics, 'metric', option)
                                # print(f"CZ class metrics comparison results are saved to {output_file_path}")
                            else:
                                logging.error('Error: No scores for climate zone class comparison')

                            if len(self.scores) > 0:
                                dir_path = os.path.join(f'{basedir}', 'output', 'scores', 'CZ_groupby',
                                                        f'{sim_source}___{ref_source}')
                                if not os.path.exists(dir_path):
                                    os.makedirs(dir_path)
                                output_file_path2 = os.path.join(dir_path,
                                                                 f'{evaluation_item}_{sim_source}___{ref_source}_scores.txt')
                                with open(output_file_path2, "w") as output_file:
                                    # Print the table header with an additional column for the overall mean
                                    output_file.write("ID\t")
                                    for i in range(1, 31):
                                        output_file.write(f"{i}\t")
                                    output_file.write("All\n")  # Move "All" to the first line
                                    output_file.write("FullName\t")
                                    for CZ_class_name in CZ_class_names.values():
                                        output_file.write(f"{CZ_class_name}\t")
                                    output_file.write("Overall\n")  # Write "Overall" on the second line

                                    # Calculate and print mean values

                                    for score in self.scores:
                                        ds = xr.open_dataset(
                                            f'{self.casedir}/output/scores/{evaluation_item}_ref_{ref_source}_sim_{sim_source}_{score}.nc')
                                        ds = Convert_Type.convert_nc(ds)
                                        output_file.write(f"{score}\t")

                                        # Calculate and write the overall mean first

                                        if self.weight.lower() == 'area':
                                            weights = np.cos(np.deg2rad(ds.lat))
                                            overall_mean = ds[score].weighted(weights).mean(skipna=True).values
                                        elif self.weight.lower() == 'mass':
                                            # Get reference data for flux weighting
                                            o = xr.open_dataset(f'{self.casedir}/output/data/{evaluation_item}_ref_{ref_source}_{ref_varname}.nc')[
                                                f'{ref_varname}']

                                            # Calculate area weights (cosine of latitude)
                                            area_weights = np.cos(np.deg2rad(ds.lat))

                                            # Calculate absolute flux weights
                                            flux_weights = np.abs(o.mean('time'))

                                            # Combine area and flux weights
                                            combined_weights = area_weights * flux_weights

                                            # Normalize weights to sum to 1
                                            normalized_weights = combined_weights / combined_weights.sum()

                                            # Calculate weighted mean
                                            overall_mean = ds[score].weighted(normalized_weights.fillna(0)).mean(skipna=True).values
                                        else:
                                            overall_mean = ds[score].mean(skipna=True).values

                                        overall_mean_str = f"{overall_mean:.3f}" if not np.isnan(overall_mean) else "N/A"

                                        for i in range(1, 31):
                                            ds1 = ds.where(CZtype == i)
                                            CZ_class_name = CZ_class_names.get(i, f"CZ_{i}")
                                            ds1.to_netcdf(
                                                f"{self.casedir}/output/scores/CZ_groupby/{sim_source}___{ref_source}/{evaluation_item}_ref_{ref_source}_sim_{sim_source}_{score}_CZ_{CZ_class_name}.nc")
                                            # Calculate and write the overall mean first
                                            if self.weight.lower() == 'area':
                                                weights = np.cos(np.deg2rad(ds.lat))
                                                mean_value = ds1[score].weighted(weights).mean(skipna=True).values
                                            elif self.weight.lower() == 'mass':
                                                # Get reference data for flux weighting
                                                o = xr.open_dataset(f'{self.casedir}/output/data/{evaluation_item}_ref_{ref_source}_{ref_varname}.nc')[
                                                    f'{ref_varname}']

                                                # Calculate area weights (cosine of latitude)
                                                area_weights = np.cos(np.deg2rad(ds.lat))

                                                # Calculate absolute flux weights
                                                flux_weights = np.abs(o.mean('time'))

                                                # Combine area and flux weights
                                                combined_weights = area_weights * flux_weights

                                                # Normalize weights to sum to 1
                                                normalized_weights = combined_weights / combined_weights.sum()

                                                # Calculate weighted mean
                                                mean_value = ds1[score].weighted(normalized_weights.fillna(0)).mean(skipna=True).values
                                            else:
                                                mean_value = ds1[score].mean(skipna=True).values

                                                # mean_value = ds1[score].mean(skipna=True).values
                                            mean_value_str = f"{mean_value:.3f}" if not np.isnan(mean_value) else "N/A"
                                            output_file.write(f"{mean_value_str}\t")
                                        output_file.write(f"{overall_mean_str}\t")  # Write overall mean
                                        output_file.write("\n")

                                selected_scores = self.scores
                                option['path'] = f"{self.casedir}/output/scores/CZ_groupby/{sim_source}___{ref_source}/"
                                option['groupby'] = 'CZ_groupby'
                                make_CZ_based_heat_map(output_file_path2, selected_scores, 'score', option)
                                # print(f"CZ class scores comparison results are saved to {output_file_path2}")
                            else:
                                logging.error('Error: No scores for climate zone class comparison')

        metricsdir_path = os.path.join(f'{casedir}', 'output', 'metrics', 'CZ_groupby')
        # if os.path.exists(metricsdir_path):
        #     shutil.rmtree(metricsdir_path)
        # print(f"Re-creating output directory: {metricsdir_path}")
        if not os.path.exists(metricsdir_path):
            os.makedirs(metricsdir_path)

        scoresdir_path = os.path.join(f'{casedir}', 'output', 'scores', 'CZ_groupby')
        if not os.path.exists(scoresdir_path):
            os.makedirs(scoresdir_path)

        try:
            _CZ_class_remap_cdo(self)
        except Exception as e:
            logging.error(f"CDO remapping failed: {e}")
            logging.info("Falling back to xarray-regrid remapping...")
            _CZ_class_remap(self)
        _scenarios_CZ_groupby(casedir, scores, metrics, sim_nml, ref_nml, evaluation_items)
