from pathlib import Path
import json
import arcpy
import pickle
import time
import os
import datetime
import yaml

import pandas as pd
import numpy as np
from arcgis.features import GeoAccessor, GeoSeriesAccessor

import data_network
from static_tools import helper_functions
from managers import settingsManager

# ADDING NEW METRICS
# Create class that inherits from the metric object
# overwrite the process function to run the calculate
# set the value of the LABEL variable to the name that will be selected by the arcgis user
# add the class name to the metric_manager METRICS list
# always needs to initialize with only the three variables


##############################################################
# LOADING THE DISTANCE MATRIX INTO A DATAFRAME
# Distance matrix file name: {scenario name}_{mode}_{pre or post network}_distance_matrix.dist
# Wide form pandas dataframe
# from column name = origin id
# all other columns are the destination ids
# stored in feather format
# use pd.from_feather(filepath) to load the dataframe
# del dataframe after use to free up memory

# CONVERT DATAFRAME TO LONGFORM FROM DISTANCE MATRIX FORM
# list of distnations dest_ids = np.delete(dataframe.columns, np.where(dataframe.columns == "from")[0])
# use pd.melt(distance_matrix_wideform, id_vars="from", value_vars=dest_ids, var_name='to', value_name='distance')


class metric(settingsManager):
    LABEL = "Label for the tool"
    DESCRIPTION = "What the tool does"
    CUMULATIVE_METRIC = "cumulative"
    DUAL_METRIC = "dual"
    def __init__(
            self, 
            projectFolder: Path, 
            scenarioName: str, 
            poi_type_list: list = None, 
            scenario_modes: list = ["walk"]
        ):
        """
        Parent class for accessibility metrics
        Args:
            projectFolder (Path): folder where the project data is written.
            projFGDB (Path): project file geodatabase where the processed OSM data is written.
            scenarioName (str): name of the scenario
            poi_type_list (list): list of the selected poi_types
            scenario_modes (list): list of the selected modes
        Returns:
            metric object
        """

        super().__init__(projectFolder, scenario_name=scenarioName)

        #Data folders:
        self.scenario_gdb_path = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb"
        self.file_path = Path(__file__).parents[0]

        #POIs:
        self.poi_table_path = self.scenario_gdb_path / self.schema_info["fc_matched_poi_table"]
        self.poi_node_field = self.schema_info["field_name_poi_nodeid"] # network node associated with the POI
        self.poi_type_field = self.schema_info["field_name_poi_type"]
        self.poi_fft_field = self.schema_info["field_name_poi_fftwalk"]
        self.poi_id_field = self.schema_info["field_name_poi_finalid"]  # unique identifier for the POI
        if poi_type_list is not None and len(poi_type_list) > 0:
            self.poi_type_list = poi_type_list
        else:
            self.poi_type_list = self.settings_info.get("scenario_categories", [])

        #Networks:
        self.scenario_label_to_code = self.settings_info["mode_name_matching"]
        self.scenario_modes = scenario_modes

        #Pre/Post:
        self.network_types = [self.schema_info["field_name_prenetwork"], self.schema_info["field_name_postnetwork"]]

        #Origins:
        self.origins_path = self.scenario_gdb_path / self.schema_info["fc_name_origin_nodes"]
        self.sync_origin_fields()
        field_exclude = {"objectid", "shape", "shape_length", "shape_area", "orig_fid", "orig_id", "join_fid", "target_fid", "join_count"}
        field_names = [field.name for field in arcpy.ListFields(str(self.origins_path)) if field.name.lower() not in field_exclude]
        data = [row for row in arcpy.da.SearchCursor(str(self.origins_path), field_names)]
        self.report_data = pd.DataFrame(data, columns=field_names)
        if self.schema_info["field_name_population"] not in field_names:
            raise ValueError(f"Error: Could not find required field '{self.schema_info['field_name_population']}' in origins feature class. Try going back and rerunning Step 2D.")
        #Nodes
        self.nodes_path = self.scenario_gdb_path / self.schema_info["fc_name_integrated_nodes"]
        self.node_id_field = self.schema_info["field_name_node_id"]

        #Scenario buffer distance
        self.scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
        distances = [row[1] for row in arcpy.da.SearchCursor(str(self.scenario_table), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_scenario_poidist"]]) if row[0] == self.scenario_name]
        if len(distances) == 1:
            self.scenario_buffer_distance_ft = distances[0]
        else:  
            arcpy.AddError(f"Error: found {len(distances)} entries for scenario {self.scenario_name} in project_scenarios table; there should be exactly 1")

        # MAIN EXECUTION
        self.origin_df = self.load_origins()


    def calculate_metrics(self, 
                         metric_type: str = CUMULATIVE_METRIC,
                         metric_args: dict = {'thresholds': [15, 30]}):
        
        timestamp = datetime.datetime.now().strftime("%y%m%d%H%M")
        run_folder = self.project_folder / self.scenario_name / f"{self.scenario_name}_{metric_type[:4]}_{timestamp}"
        run_folder.mkdir(parents=True, exist_ok=True)

        # Compute the metrics by mode
        for mode in self.scenario_modes:
            start_time = time.time()
            metrics_results = [] # initialize an object to hold results for all poi_types
            
            for network in self.network_types:
                arcpy.AddMessage(f"Getting {network} {mode} {metric_type} data")
                metrics_results.append(self.get_metric(mode, network, metric_type, metric_args))

            arcpy.AddMessage(f"Saving {mode} {metric_type} metrics to {run_folder}")
            print("Saving results")
            output_path = (
                run_folder / f"{self.scenario_name}_{mode}_{metric_type[:4]}.metrics"
            )

            results_df = pd.concat(metrics_results)
            results_df[self.schema_info["field_name_origin_id"]] = results_df[self.schema_info["field_name_origin_id"]].astype(str)

            self.report_data[self.schema_info["field_name_origin_id"]] = self.report_data[self.schema_info["field_name_origin_id"]].astype(str)

            joined_df = results_df.merge(
                self.report_data,
                left_on=self.schema_info["field_name_origin_id"],
                right_on=self.schema_info["field_name_origin_id"],
                how="left"
            )

            numeric_cols = joined_df.select_dtypes(include=['number']).columns
            joined_df[numeric_cols] = joined_df[numeric_cols].fillna(1)

            cols_to_drop = [self.schema_info["field_name_origin_name"], "OBJECTID", "Shape", "Shape_Length", "Shape_Area"]
            joined_df = joined_df.drop(columns=cols_to_drop, errors="ignore")

            with open(output_path, 'wb') as file:
                pickle.dump(joined_df, file, protocol=4)

            csv_path = output_path.with_suffix('.csv')
            joined_df.to_csv(csv_path, index=False)

            end_time = time.time()
            elapsed_time = (end_time - start_time) / 60
            arcpy.AddMessage(f"{elapsed_time} minutes elapsed")
            print(f"{elapsed_time} minutes elapsed")

    def load_pois_and_filter(self):
        arcpy.AddMessage(f"Loading and filtering POI table: {self.poi_table_path}")
        poi_rows = []
        with arcpy.da.SearchCursor(
            str(self.poi_table_path),
            [self.poi_node_field, self.poi_type_field, self.poi_fft_field, self.poi_id_field], 
        ) as cursor:
            for row in cursor:
                if row[1] in self.poi_type_list: #filter by POI type
                    poi_rows.append(
                        {
                            self.poi_node_field: row[0],
                            self.poi_type_field: row[1],
                            self.poi_fft_field: row[2],
                            self.poi_id_field: row[3],
                        }
                    )
        poi_df = pd.DataFrame(poi_rows)
        return poi_df

    def load_origins(self):
        arcpy.AddMessage(f"Loading origins table: {self.origins_path}")
        origin_rows = []
        with arcpy.da.SearchCursor(
            str(self.origins_path),
            [self.schema_info["field_name_origin_id"]]
        ) as cursor:
            for row in cursor:
                origin_rows.append({self.schema_info["field_name_origin_id"]: row[0]})
                
        origin_df = pd.DataFrame(origin_rows)
        return origin_df
    
    def load_distance_matrix(self, mode: str, network: str):
        lbl = "pre" if network == "prenetwork" else "post"
        file_path = (
            self.project_folder / self.scenario_name 
            / f"{self.scenario_name}_{mode}_{lbl}_dist_matrix.dist"
        )
        wide = pd.read_feather(file_path)

        return wide

    def sync_origin_fields(self):
        """Ensures polygon and point origin layers have identical fields."""
        origin_type_val = "Custom Points" 
        with arcpy.da.SearchCursor(str(self.scenario_table), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_origin_type"]]) as cursor:
            for row in cursor:
                if row[0] == self.scenario_name:
                    if row[1]: 
                        origin_type_val = str(row[1])
                    break
        
        poly_fc = None
        if "Census Blocks" in origin_type_val:
            poly_fc = str(self.scenario_gdb_path / self.schema_info["fc_name_census_block_prj"])
        elif "Custom Polygons" in origin_type_val:
            poly_fc = str(self.scenario_gdb_path / self.schema_info["fc_name_custom_origin_polygons"])
        
        pts_fc = str(self.origins_path)
            
        if poly_fc and arcpy.Exists(poly_fc):
            
            system_skips = {
                "objectid", "fid", "shape", "shape_length", "shape_area", 
                "orig_fid", "join_fid", "join_count", "target_fid"
            }
            
            # Get dictionaries of field names, excluding OID and Geometry
            poly_fields = {
                f.name.lower(): f.name for f in arcpy.ListFields(poly_fc) 
                if f.type not in ['OID', 'Geometry'] and f.name.lower() not in system_skips
            }
            pts_fields = {
                f.name.lower(): f.name for f in arcpy.ListFields(pts_fc) 
                if f.type not in ['OID', 'Geometry'] and f.name.lower() not in system_skips
            }
            
            # Find discrepancies
            missing_in_pts = [name for lower, name in poly_fields.items() if lower not in pts_fields]
            missing_in_poly = [name for lower, name in pts_fields.items() if lower not in poly_fields]
            
            origin_id_fld = self.schema_info["field_name_origin_id"]
            
            # Two-way sync using JoinField
            if missing_in_pts:
                arcpy.AddMessage(f"Syncing fields from polygons to points: {missing_in_pts}")
                arcpy.management.JoinField(pts_fc, origin_id_fld, poly_fc, origin_id_fld, missing_in_pts)
            if missing_in_poly:
                arcpy.AddMessage(f"Syncing fields from points to polygons: {missing_in_poly}")
                arcpy.management.JoinField(poly_fc, origin_id_fld, pts_fc, origin_id_fld, missing_in_poly)

    def get_metric(self, 
                    mode: str, 
                    network: str,
                    metric_type: str,
                    metric_args: dict):
        
        # TODO: check if we already have a pickle file of this computation;
        # don't recompute unless the users requests to overwrite it

        print("Loading POIS")
        self.poi_df = self.load_pois_and_filter()
        print(f"Calculating {metric_type} metrics for {mode} {network} ...")
        print("Loading distance matrix")
        # Only load the distance matrix once, since this can take a while
        distance_matrix_wide = self.load_distance_matrix(mode, network)
        # dist_matrix.set_index(['to_osmid'], inplace=True) # speed up the merge to poi_df
        # self.poi_df.set_index(['node_osmid'], inplace=True)
        # Note: some of our network nodes can have 'post' in their names, so they need to be cast as string

        all_poi_results = []

        # iterate by poi_type so the join is smaller
        for poi_type in self.poi_type_list:
            print(f"POI Type: {poi_type}")
            # filter poi table for a specific poi_type
            poi_df_filtered = self.poi_df.query(f"{self.poi_type_field} == '{poi_type}'")

            # Melt distance matrix into long format, dropping node IDs from the distance matrix 
            # that do not have any relevant POIs for this poi_type associated with them
            poi_relevant_nodes = poi_df_filtered[self.poi_node_field].unique()
            dest_cols_to_melt = set(distance_matrix_wide.columns).intersection(poi_relevant_nodes)

            arcpy.AddMessage(f"Melting distances matrix for {poi_type}")
            #print("Melting distance matrix")
            distance_matrix = pd.melt(
                distance_matrix_wide,
                id_vars="from",
                value_vars=dest_cols_to_melt,
                var_name="to",
                value_name="distance",
            )
            
            distance_matrix = distance_matrix[np.isfinite(distance_matrix['distance'])]
                
            arcpy.AddMessage(f"Joining distance matrix to nodes for {poi_type}")
            #print("Joining data tables")
            metrics_framework = distance_matrix.merge(
                poi_df_filtered,
                how = "inner",
                left_on = "to",
                right_on = self.poi_node_field

                # left_index = True,
                # right_index = True
            )
            
            #Calculating final travel time that incorporates walk time from node to POI
            metrics_framework["travel_time_sec"] = metrics_framework["distance"] + metrics_framework["fft_walk"]
            
            if metric_type == metric.CUMULATIVE_METRIC:
                #print("Calculating aggregates")
                agg_cols = []
                agg_dict = {}
                for t in metric_args["thresholds"]:
                    arcpy.AddMessage(f"Calculating cumulative metrics for {poi_type} and {t} minute travel time")
                    metrics_framework[f"within_{t}"] = np.where(metrics_framework["travel_time_sec"] <= t*60, 
                                                                    metrics_framework[self.poi_id_field],
                                                                    None)
                    agg_cols.append(f"within_{t}")
                    # assemble a dictionary we can pass to agg() function below to get unique counts of POI nodes for each threshold
                    agg_dict[f"within_{t}"]="nunique" 

                poi_type_results = metrics_framework.groupby(["from"]).agg(agg_dict)
                poi_type_results = poi_type_results.reset_index()


            elif metric_type == metric.DUAL_METRIC:
                # Take the min(travel time) for each origin, poi_id (to deal with uniqueness issues where the same
                # origin could reach the same poi via multiple different network egress nodes
                
                arcpy.AddMessage(f"Calculating dual metric for {poi_type}")
                
                metrics_framework_min_time_per_poi = (
                    metrics_framework
                    .sort_values(["from", self.poi_id_field, "travel_time_sec"])
                    .drop_duplicates(["from", self.poi_id_field], keep="first") # keep the min travel time per origin, POI combination
                    .sort_values(["from", "travel_time_sec"]) # need to sort again, this time reshuffling POIs from nearest to farthest from each origin
                    .groupby(["from"])
                    .nth(metric_args[poi_type]-1) # this is the Nth number the user selects for a given POI type
                )

                poi_type_results = metrics_framework_min_time_per_poi.filter(["from", "travel_time_sec"])
                poi_type_results = poi_type_results.reset_index(drop=True)
                poi_type_results["nth_destination"] = metric_args[poi_type]
            else:
                # TODO: raise error to ArcGIS log
                pass

            # Join back to origins_df and set all Null values to 0, so we don't drop origins from our results
            poi_type_results_all_origins = self.origin_df.merge(
                poi_type_results,
                how = "left",
                left_on = self.schema_info["field_name_origin_id"],
                right_on = "from"
            )
            
            poi_type_results_all_origins.drop(columns=["from"], inplace=True)

            if metric_type == metric.CUMULATIVE_METRIC:
                poi_type_results_all_origins[agg_cols] = poi_type_results_all_origins[agg_cols].fillna(0)
            if metric_type == metric.DUAL_METRIC:
                #Note: If origin cannot reach any Nth destination, value left as NA/Null; this is handled later on in metrics_report.py
                poi_type_results_all_origins["nth_destination"] = poi_type_results_all_origins["nth_destination"].fillna(metric_args[poi_type])

            poi_type_results_all_origins['mode'] = mode
            poi_type_results_all_origins['network'] = network
            poi_type_results_all_origins['poi_type'] = poi_type
            
            all_poi_results.append(poi_type_results_all_origins)
    
        return pd.concat(all_poi_results)

    # metric_args format
    # {"origin_ids": ["GEOID_250173539002009"], "thresholds": [15]}
    def calc_travel_sheds(self, metric_args: dict, debug: bool = False):
        metric_args["thresholds"] = sorted(metric_args["thresholds"], reverse=True)
        for mode in metric_args["modes"]:
            for network_type in metric_args["networktypes"]:
                lbl_short = "pre" if network_type == "prenetwork" else "post"
                distance_matrix_wide = self.load_distance_matrix(mode, network_type)
                sedf_nodes = pd.DataFrame.spatial.from_featureclass(location = str(self.nodes_path))
                sedf_nodes[self.node_id_field] = sedf_nodes[self.node_id_field].astype(str)
                # Save the result to a feature class within our scenario gdb
                travel_shed_fc = f"travel_sheds_{mode}_{lbl_short}"
                travel_shed_sr = arcpy.Describe(str(self.nodes_path)).spatialReference
                travel_shed_fc_path = self.scenario_gdb_path / travel_shed_fc

                if not arcpy.Exists(str(travel_shed_fc_path)):
                    arcpy.management.CreateFeatureclass(
                        str(self.scenario_gdb_path), 
                        str(travel_shed_fc),
                        geometry_type="POLYGON", 
                        spatial_reference=travel_shed_sr
                        )
                    arcpy.management.AddFields(str(travel_shed_fc_path), [
                        ["mode", "TEXT", "mode", 255],
                        ["network", "TEXT", "network", 255],
                        ["origin_id","TEXT", "origin_id", 255],
                        ["threshold", "DOUBLE", "threshold", None],
                        ["area", "DOUBLE", "area", None]
                        ])
                else:
                    arcpy.AddMessage(f"Appending to feature class: {travel_shed_fc}")
                for origin_id in metric_args["origin_ids"]:
                    for threshold in metric_args["thresholds"]:
                        # TODO handle multiple runs on same mode/network; 
                        # let user clear out existing feature class or run in "append" mode
                        # first check if origin_id/threshold pair already appear in fc, if so skip
                        wc = f"origin_id = '{origin_id}' and threshold = {threshold}"
                        match = False
                        with arcpy.da.SearchCursor(str(travel_shed_fc_path), ["origin_id","threshold"], wc) as cur:
                            for row in cur:
                                match = True
                        if match:
                            arcpy.AddMessage(f"skipping {origin_id} with threshold {threshold} minutes, already calcuated")
                            break

                        # Which network nodes fall within the travel shed threshold?
                        # we only care about a single row in the wide matrix - corresponding to the origin id we're calculating for
                        distance_matrix = distance_matrix_wide[distance_matrix_wide["from"] == origin_id]
                        distance_matrix = pd.melt(
                                distance_matrix,
                                id_vars="from",
                                var_name="to",
                                value_name="distance",
                        )
                        nodes_in_shed = distance_matrix[distance_matrix["distance"] <= threshold*60]
                        node_ids_in_shed = list(nodes_in_shed["to"].astype(str))
                        
                        sedf_filtered = (
                            sedf_nodes[sedf_nodes[self.node_id_field].isin(node_ids_in_shed)]
                                .merge(
                                    distance_matrix,
                                    left_on=self.node_id_field,
                                    right_on="to"
                                )
                                .filter([self.node_id_field, "distance", "SHAPE"])
                        )

                        arcpy.AddMessage(f"Calculating {network_type} {mode} travel shed for origin {origin_id} with threshold {threshold} minutes, {len(node_ids_in_shed)} nodes in shed")
        
                        # calculate buffer distance, for most nodes it'll be 3 min of walking
                        # unless that is outside the threshold
                
                        walk_feet = self.scenario_buffer_distance_ft
                        # crs is UTM (meters), convert 3 min of walking at walk speed to meters of buffer
                        # meters * (miles/meter) * (hours / mile) * (seconds / hour)
                        default_buffer_meters = walk_feet * 0.3048
                        default_buffer_seconds = default_buffer_meters * (1/1609.34) * (1/self.settings_info["default_values"]["speed_pedestrian"]) * 3600
                        sedf_filtered["buff_dist"] = np.where((threshold*60) - sedf_filtered['distance'] < default_buffer_seconds,
                                                    default_buffer_meters * ((threshold*60) - sedf_filtered['distance']) / default_buffer_seconds,
                                                    default_buffer_meters)
                        
                        if sedf_filtered.empty or not sedf_filtered[self.node_id_field].notna().any():
                            arcpy.AddMessage(f"No network nodes found in travel shed for origin {origin_id}, threshold {threshold}. Skipping buffers/export.")

                            arcpy.management.Delete("memory")  # cleanup memory
                            continue   
                        else:
                            sedf_filtered.spatial.to_featureclass(r"memory\network_nodes_in_travelshed")

                        if "buff_dist_num" not in [f.name for f in arcpy.ListFields(r"memory\network_nodes_in_travelshed")]:
                            arcpy.management.AddField(r"memory\network_nodes_in_travelshed", "buff_dist_num", "DOUBLE")
                        arcpy.management.CalculateField(r"memory\network_nodes_in_travelshed", "buff_dist_num", "!buff_dist!", "PYTHON3")

                        arcpy.analysis.PairwiseBuffer(
                            in_features=r"memory\network_nodes_in_travelshed",
                            out_feature_class=r"memory\buff_dis",
                            buffer_distance_or_field="buff_dist_num",
                            dissolve_option="ALL",
                            dissolve_field=None,
                            method="GEODESIC",
                            max_deviation="0 Meters"
                        )

                        arcpy.analysis.Clip(
                            in_features = r"memory\buff_dis",
                            clip_features= str(self.project_fgdb / self.schema_info["land_area"]),
                            out_feature_class=r"memory\buff_dis_clip")

                        # calculate the area of the travel shed
                        arcpy.management.CalculateGeometryAttributes(
                            in_features=r"memory\buff_dis_clip",
                            geometry_property="area AREA_GEODESIC",
                            area_unit="SQUARE_MILES_US",
                            coordinate_system=None,
                            coordinate_format="SAME_AS_INPUT"
                        )

                        # def buffer_by_row(row):
                        #     buff_dist = row["buff_dist"]
                        #     return row["SHAPE"].buffer(buff_dist)
                        # sedf_filtered["buffered"] = sedf_filtered.apply(buffer_by_row,axis=1)
                        # sedf_filtered.spatial.set_geometry("buffered")

                        # # write to output fc
                        # sedf_filtered[["buffered"]].spatial.to_featureclass(r"memory\buff")
                        # # for testing: write undissolved to disk
                        # if debug:
                        #     arcpy.management.CopyFeatures(r'memory\buff', os.path.join(os.getcwd(),"buff_tmp.shp"))
                        # arcpy.management.Dissolve(r"memory\buff", r"memory\buff_dis")
                        
                        # fc = str(travel_shed_fc)
                        # required_fields = [
                        #     ("mode", "TEXT", None, 255),
                        #     ("network", "TEXT", None, 255),
                        #     ("origin_id", "TEXT", None, 255),
                        #     ("threshold", "DOUBLE", None, None),
                        # ]

                        # existing_fields = [f.name for f in arcpy.ListFields(fc)]

                        # for fname, ftype, falias, flen in required_fields:
                        #     if fname not in existing_fields:
                        #         arcpy.AddMessage(f"Adding missing field '{fname}' to {fc}")
                        #         if ftype == "TEXT":
                        #             arcpy.management.AddField(fc, fname, ftype, field_length=flen, field_alias=falias or fname)
                        #         else:
                        #             arcpy.management.AddField(fc, fname, ftype, field_alias=falias or fname)



                        with arcpy.da.InsertCursor(str(travel_shed_fc_path) ,["mode", "network", "origin_id", "threshold", "area", "SHAPE@"]) as cur_w:
                            with arcpy.da.SearchCursor(r"memory\buff_dis_clip", ["area", "SHAPE@"]) as cur_r:
                                for row_r in cur_r:
                                    row_w = (str(mode), str(network_type), str(origin_id), float(threshold), row_r[0], row_r[1])
                                    cur_w.insertRow(row_w)
                        
                        arcpy.management.Delete("memory")
                #reorder shapes based on threshold
                arcpy.AddMessage("Sorting the travel sheds.")
                arcpy.management.Sort(str(travel_shed_fc_path), "memory/sorted_sheds", sort_field="threshold DESCENDING", spatial_sort_method="UR")
                arcpy.management.Delete(str(travel_shed_fc_path))
                arcpy.management.CopyFeatures("memory/sorted_sheds", str(travel_shed_fc_path))
                arcpy.management.Delete("memory")


    def calc_density_maps(self, metric_args: dict, cellSize:int = 30, bandwidth:float=300, debug: bool = False):
        timestamp = datetime.datetime.now().strftime("%y%m%d%H%M")
        density_gdb_name =  f"density_data_{timestamp}.gdb"
        density_gdb_path = helper_functions.drop_add_fgdb(self.project_folder / self.scenario_name, density_gdb_name)
        sedf_node_match = pd.DataFrame.spatial.from_table(str(self.poi_table_path))
        
        for mode in metric_args["modes"]:
            for network_type in metric_args["networktypes"]:
                distance_matrix_wide = self.load_distance_matrix(mode, network_type)
                sedf_nodes = pd.DataFrame.spatial.from_featureclass(location = str(self.nodes_path))
                sr = arcpy.SpatialReference(sedf_nodes.spatial.sr['wkid'])
                sedf_nodes[self.node_id_field] = sedf_nodes[self.node_id_field].astype(str)

                for origin_id in metric_args["origin_ids"]:
                    for threshold in metric_args["thresholds"]:
                        # Which network nodes fall within the travel shed threshold?
                        # we only care about a single row in the wide matrix - corresponding to the origin id we're calculating for
                        distance_matrix = distance_matrix_wide[distance_matrix_wide["from"] == origin_id]
                        distance_matrix = pd.melt(
                                distance_matrix,
                                id_vars="from",
                                var_name="to",
                                value_name="distance",
                        )
                        nodes_in_shed = distance_matrix[distance_matrix["distance"] <= threshold*60]
                        node_ids_in_shed = list(nodes_in_shed["to"].astype(str))
                        
                        sedf_nodes_copy = sedf_nodes[sedf_nodes[self.node_id_field].isin(node_ids_in_shed)].copy()


                        arcpy.AddMessage(f"Calculating {network_type} {mode} density for origin {origin_id} with threshold {threshold} minutes, {len(node_ids_in_shed)} nodes in shed")
                        sedf_nodes_copy['YCoord'] = sedf_nodes_copy['SHAPE'].apply(lambda shape: shape.y)
                        sedf_nodes_copy['XCoord'] = sedf_nodes_copy['SHAPE'].apply(lambda shape: shape.x)
                        sedf_node_match_copy = sedf_node_match[sedf_node_match[self.poi_node_field].isin(node_ids_in_shed)].copy()
                        sedf_node_count = sedf_node_match_copy.groupby(self.poi_node_field)[self.poi_id_field].count().reset_index()
                        sedf_nodes_copy = sedf_nodes_copy.merge(sedf_node_count,
                                                            left_on=self.node_id_field,
                                                            right_on=self.poi_node_field)
                        half_cell = int(cellSize/2)
                        x_centers = np.arange(sedf_nodes_copy['XCoord'].min()+half_cell, sedf_nodes_copy['XCoord'].max(),cellSize)
                        y_centers = np.arange(sedf_nodes_copy['YCoord'].min()+half_cell, sedf_nodes_copy['YCoord'].max(),cellSize)
                        point_coords = sedf_nodes_copy[['XCoord','YCoord']].values
                        counts = sedf_nodes_copy[self.poi_id_field].values
                        density_grid = []
                        for y in y_centers:
                            row = []
                            for x in x_centers:
                                dist = np.linalg.norm(point_coords - np.array([x,y]), axis=1)
                                weights = counts[dist<bandwidth]
                                dist = dist[dist < bandwidth]
                                
                                if len(dist)>0:
                                    dist = np.square(1 - np.square(dist / bandwidth))
                                    dist = (3/np.pi) * weights * dist
                                    density = np.sum(dist)/(bandwidth*bandwidth)
                                    density = density / (cellSize * cellSize)
                                    row.append(density)
                                else:
                                    row.append(-1)
                            density_grid.append(row)
                        
                        origin = arcpy.Point(x_centers[0], y_centers[0])
                        arcpy.env.outputCoordinateSystem = sr
                        arcpy.env.mask = str(str(self.project_fgdb / self.schema_info["land_area"]))
                        raster = arcpy.NumPyArrayToRaster(np.array(density_grid), origin, cellSize, cellSize, value_to_nodata=-1)
                        raster.save(str(density_gdb_path / f"{origin_id}_{mode}_{network_type}_{threshold}"))
                        del raster
        return density_gdb_path

    def process(self):
        pass