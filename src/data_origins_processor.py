
from pathlib import Path
import arcpy

import json
import yaml
import os
import pickle
from collections import Counter
import time
from datetime import datetime


import numpy as np
import pandas as pd
from arcgis.features import GeoAccessor, GeoSeriesAccessor

from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import shortest_path
from scipy.spatial import KDTree
from scipy.spatial import Delaunay
from scipy.spatial import distance

import multiprocessing as mp
from operator import itemgetter

from static_tools import helper_functions
from static_tools import random_id


import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import seaborn as sns
from typing import Literal
import math
import uuid
from managers import settingsManager



class connectors(settingsManager):

    def __init__(self, projectFolder:Path, scenario_name:str):
        """
            
            Args:
                projectFolder (Path): folder where the project data is written.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                
        """
        super().__init__(projectFolder, scenario_name=scenario_name)

        self.scenario_folder = self.project_folder / self.scenario_name
        self.scenario_fgdb = self.scenario_folder / f"{self.scenario_name}.gdb"
        self.fc_census = self.scenario_fgdb / self.schema_info["fc_name_census_block_prj"]

        self.origin_centroids = None
        self.index_to_origin_id = {}
        self.origin_centroid_coords = []
        self.origin_centroid_indices = []

        self.set_fft()
        self.is_custom = not arcpy.Exists(str(self.fc_census))

    
    def set_fft(self):
        """
        Sets the mapping of modes to their corresponding free-flow travel time (fft) fields.
        """
        self.weight_fields = {
            self.schema_info["field_name_vehicle_mode"]: self.schema_info["field_name_fft_vehicle"],
            self.schema_info["field_name_truck_mode"]: self.schema_info["field_name_fft_truck"],
            self.schema_info["field_name_pedestrian_mode"]: self.schema_info["field_name_fft_ped"],
            self.schema_info["field_name_bicycle_mode"]: self.schema_info["field_name_fft_bike"],
            self.schema_info["field_name_p_pedestrian_mode"]: self.schema_info["field_name_fft_ped"],
            self.schema_info["field_name_p_bicycle_mode"]: self.schema_info["field_name_fft_p_bike"]
        }

    def build_origins(self, orig_type, radius_origin, custom_data, output_path, messages, orig_lat=None, orig_lon=None):
        from static_tools import random_id
        import data_downloader

        arcpy.AddMessage(f"Generating {orig_type} origins...")
        
        #Remove previous census origin datasets and all centroid points generated on prior runs. This prepares the geodatabase space for new origin download
        census_names = [self.schema_info["fc_name_census_block_prj"], self.schema_info["fc_name_census_block"]]
        for c_name in census_names:
            old_census = str(self.scenario_fgdb / c_name)
            if arcpy.Exists(old_census):
                arcpy.management.Delete(old_census)
                
        fc_base = self.schema_info["fc_name_origin_nodes"]
        for prefix in ["", "buffered_", "metrics_"]:
            stale_fc = str(self.scenario_fgdb / f"{prefix}{fc_base}")
            if arcpy.Exists(stale_fc):
                arcpy.management.Delete(stale_fc)

        out_fc = str(self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"])

        #Origin logic for Census blocks
        if orig_type == "Census Blocks":
            if orig_lat is not None and orig_lon is not None:
                centroid_y = orig_lat
                centroid_x = orig_lon
            else:
                scenario_coverage = [row[0] for row in arcpy.da.SearchCursor(str(self.scenario_fgdb / "scenario_coverage_area"), ["SHAPE@"])][0]
                sr = scenario_coverage.spatialReference
                scenario_coverage_ll = scenario_coverage.projectAs(helper_functions.get_wgs84_sr())
                centroid_y = scenario_coverage_ll.centroid.Y
                centroid_x = scenario_coverage_ll.centroid.X
            
            ll_lat, ll_long = helper_functions.offset_lat_lon(centroid_y, centroid_x, -1*radius_origin, -1*radius_origin)
            ur_lat, ur_long = helper_functions.offset_lat_lon(centroid_y, centroid_x, radius_origin, radius_origin)
            
            dlcb = data_downloader.census_blocks(output_path, messages)
            fc = dlcb.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, self.scenario_fgdb, self.utmsr.factoryCode)
            arcpy.AddMessage("Filtering zero-population blocks...")
            lyr = arcpy.SelectLayerByAttribute_management(str(fc), "NEW_SELECTION", f"{self.schema_info['field_name_population']} = 0").getOutput(0)
            arcpy.DeleteFeatures_management(lyr)
            
            census_prj = str(self.scenario_fgdb / self.schema_info["fc_name_census_block_prj"])
            if not arcpy.Exists(census_prj):
                # CRITICAL FIX: Project to UTM instead of just CopyFeatures
                arcpy.AddMessage(f"Projecting census blocks to {self.utmsr.name}...")
                arcpy.management.Project(fc, census_prj, self.utmsr) 

            # Add and populate the ID fields on the POLYGONS first
            helper_functions.drop_add_field(census_prj, self.schema_info["field_name_origin_id"], "TEXT")
            with arcpy.da.UpdateCursor(census_prj, ["GEOID", self.schema_info["field_name_origin_id"]]) as uc:
                for row in uc:
                    raw_val = str(row[0])
                    row[1] = f"GEOID_{raw_val}" 
                    uc.updateRow(row)
            
            arcpy.management.AlterField(census_prj, "GEOID", self.schema_info["field_name_origin_name"])

            # Generate centroids from the fully attributed polygons
            arcpy.AddMessage("Generating centroids...")
            if arcpy.Exists(out_fc): arcpy.management.Delete(out_fc)
            arcpy.management.FeatureToPoint(census_prj, out_fc, "INSIDE")
            
            arcpy.AddMessage("Census blocks generated successfully.")

        #Origin logic for custom points or polygons
        else:
            arcpy.AddMessage("Handling custom origins...")
            target_name = self.schema_info["fc_name_custom_origin_polygons"] if orig_type == "Custom Polygons" else self.schema_info["fc_name_custom_origin_points"]
            target_path = str(self.scenario_fgdb / target_name)

            # CRITICAL FIX: Ensure custom data is projected to UTM
            desc = arcpy.Describe(custom_data)
            if desc.spatialReference.factoryCode != self.utmsr.factoryCode:
                arcpy.AddMessage(f"Projecting custom data to {self.utmsr.name}...")
                arcpy.management.Project(custom_data, target_path, self.utmsr)
            else:
                if desc.catalogPath != target_path:
                    arcpy.management.CopyFeatures(custom_data, target_path)
            
            # Apply fields and IDs directly to the Base Geometry
            for f in self.schema_info["origins_fields"]:
                f["featureClass"] = target_path
                helper_functions.drop_add_field(**f)
            
            cursor_fields = [
                self.schema_info["field_name_population"], 
                self.schema_info["field_name_housing_units"], 
                self.schema_info["field_name_origin_id"], 
                self.schema_info["field_name_origin_name"]
            ]
            
            used_ids = []
            with arcpy.da.UpdateCursor(target_path, cursor_fields) as uc:
                for row in uc:
                    # Population fallback
                    row[0] = row[0] if row[0] else 1
                    # Housing units fallback
                    row[1] = row[1] if row[1] else 1
                    
                    # Generate a clean ID based on the origin_name (or default to "Custom")
                    raw_name = f"{str(row[3]).strip()}_" if row[3] else "custom_"
                    new_id = random_id.create_random_id(raw_name.replace(" ", "_"), used_ids)
                    used_ids.append(new_id)

                    # Update IDs and Names
                    row[2] = new_id # origin_id field
                    uc.updateRow(row)

            # Generate points AFTER IDs are applied so they inherit the exact same attributes
            if orig_type == "Custom Polygons":
                if arcpy.Exists(out_fc): arcpy.management.Delete(out_fc)
                arcpy.management.FeatureToPoint(target_path, out_fc, "INSIDE")

            if orig_type == "Custom Points":
                arcpy.management.Delete(str(self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"]))
                arcpy.management.CopyFeatures(target_path, str(self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"]))

            arcpy.AddMessage(f"{orig_type} processed successfully.")


    def get_origin_centroids(self):
        arcpy.AddMessage("Loading origin points into memory...")
        self.fc_nodes_output = self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"]
        
        # FIX: Add 'spatial_reference=self.utmsr' to force on-the-fly projection to UTM!
        with arcpy.da.SearchCursor(str(self.fc_nodes_output), ["SHAPE@XY", self.schema_info["field_name_origin_id"]], spatial_reference=self.utmsr) as sc:
            self.origin_centroids = {row[1]: row[0] for row in sc}
            
        for i, (k, v) in enumerate(self.origin_centroids.items()):
            self.index_to_origin_id[i] = k
            self.origin_centroid_coords.append(v)
            self.origin_centroid_indices.append(i)

    def create_output_fcs(self):

        self.fc_ways_output = self.scenario_fgdb / self.schema_info["fc_name_integrated_network"]
        arcpy.AddMessage("Removing old centroid connectors....")
        lyr = arcpy.SelectLayerByAttribute_management(str(self.fc_ways_output), "NEW_SELECTION", f"{self.schema_info['field_name_highway']} = 'centroid_connector'").getOutput(0)
        arcpy.DeleteFeatures_management(lyr)

        self.fc_nodes_output = self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"]

        self.fc_dt_temp = helper_functions.drop_add_featureclass(self.scenario_fgdb, "connectors_graph", "POLYLINE", self.utmsr,"32_BIT") #oid must be 32 bit to be compatible with Network Analyst
        helper_functions.drop_add_field(self.fc_dt_temp, self.schema_info["field_name_origin_name"], "TEXT")
        helper_functions.drop_add_field(self.fc_dt_temp, "mode", "TEXT")
        helper_functions.drop_add_field(self.fc_dt_temp, "network", "TEXT")
        
    def remove_from_water(self):
        arcpy.AddMessage("Removing connectors that cross bodies of water.")
        if arcpy.Exists(str(self.project_fgdb / self.schema_info["fc_name_water_utm"])):
            lyr = arcpy.SelectLayerByLocation_management(str(self.fc_ways_output), "INTERSECT", str(self.project_fgdb / self.schema_info["fc_name_water_utm"]), None, "NEW_SELECTION").getOutput(0)
            where_clause = f"{self.schema_info['field_name_highway']} = 'centroid_connector'"
            lyr = arcpy.SelectLayerByAttribute_management(lyr, "SUBSET_SELECTION", where_clause).getOutput(0)
            arcpy.DeleteFeatures_management(lyr)

            lyr2 = arcpy.SelectLayerByLocation_management(str(self.fc_dt_temp), "INTERSECT", str(self.project_fgdb / self.schema_info["fc_name_water_utm"]), None, "NEW_SELECTION").getOutput(0)
            arcpy.DeleteFeatures_management(lyr2)
            
    def remove_from_highway(self):
        arcpy.AddMessage("Removing connectors that cross major highways.")
        ways_fc = str(self.fc_ways_output)
        hwy_fld = self.schema_info['field_name_highway']
        
        # 1. Safely isolate the highways into a temporary memory layer
        hwy_types = "('motorway', 'motorway_link', 'trunk', 'trunk_link')"
        hwy_wc = f"{hwy_fld} IN {hwy_types}"
        barrier_lyr = arcpy.management.MakeFeatureLayer(ways_fc, "hwy_barriers", hwy_wc).getOutput(0)
        
        # 2. Select ways that intersect the barrier layer
        lyr = arcpy.management.SelectLayerByLocation(ways_fc, "INTERSECT", barrier_lyr, selection_type="NEW_SELECTION").getOutput(0)
        
        # 3. Subset to ONLY the connectors, then delete
        wc_conn = f"{hwy_fld} = 'centroid_connector'"
        lyr = arcpy.management.SelectLayerByAttribute(lyr, "SUBSET_SELECTION", wc_conn).getOutput(0)
        if int(arcpy.management.GetCount(lyr)[0]) > 0:
            arcpy.management.DeleteFeatures(lyr)
        
        # 4. Clean up diagnostic layer
        if arcpy.Exists(str(self.fc_dt_temp)):
            lyr2 = arcpy.management.SelectLayerByLocation(str(self.fc_dt_temp), "INTERSECT", barrier_lyr, selection_type="NEW_SELECTION").getOutput(0)
            arcpy.management.DeleteFeatures(lyr2)
            
        # Clean up memory
        arcpy.management.Delete(barrier_lyr)
    
    def create_connectors_nn(self, modes:list, prenetwork:bool=True, postnetwork:bool=True, orig_type: str = None):
        networks = []
        if prenetwork is True:
            networks.append("prenetwork")
        if postnetwork is True:
            networks.append("postnetwork")

        junctions = self.scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]
        connector_edges_to_insert = {}

        for m in modes:
            for pn in networks:
                arcpy.AddMessage(f"Creating connector for {m} in the {pn}.")
                wc = f"{m} = 1 and {pn} = 1 and {self.schema_info['field_name_motorway']} = 0"
                arcpy
                fft_name = self.weight_fields[m]
                offset = len(self.origin_centroid_coords)
                index_to_osmid = {}
                all_coords = [c for c in self.origin_centroid_coords]
                
                census_fc = str(self.scenario_fgdb / self.schema_info["fc_name_census_block_prj"])
                custom_poly_fc = str(self.scenario_fgdb / self.schema_info["fc_name_custom_origin_polygons"])
                
                if orig_type == "Census Blocks" and arcpy.Exists(census_fc):
                    origin_fc = census_fc
                    search_dist = "100 Feet"
                elif orig_type == "Custom Polygons" and arcpy.Exists(custom_poly_fc):
                    origin_fc = custom_poly_fc
                    search_dist = "100 Feet"  # Tighter radius for custom polygons
                else:
                    origin_fc = str(self.fc_nodes_output)
                    search_dist = "2500 Feet"

                lyr = arcpy.SelectLayerByLocation_management(str(junctions), "INTERSECT", origin_fc, search_dist, "NEW_SELECTION").getOutput(0)
                lyr = arcpy.SelectLayerByAttribute_management(lyr, "SUBSET_SELECTION", wc).getOutput(0)
                with arcpy.da.SearchCursor(lyr, ["SHAPE@XY", self.schema_info["field_name_node_id"]]) as sc:
                    index = offset
                    for row in sc:
                        all_coords.append(row[0])
                        index_to_osmid[index] = row[1]
                        index += 1
                all_coords = np.array(all_coords)
                tri = Delaunay(all_coords)
                #census_nodes_to_insert = []
                
                for t in tri.simplices:
                    if any(x in self.origin_centroid_indices for x in t):
                        matches = np.isin(t,np.array(self.origin_centroid_indices))
                        centroid = t[matches][0]
                        geoid = self.index_to_origin_id[centroid]
                        edge_id = f"{geoid}"
                        for j in t[~matches]:
                            osmid = None
                            if j in index_to_osmid:
                                osmid = index_to_osmid[j]
                            if osmid is not None:
                                edge = (edge_id, osmid)
                                d = np.linalg.norm(all_coords[centroid] - all_coords[j])
                                if edge not in connector_edges_to_insert:
                                    connector_edges_to_insert[edge] = {"ids":[all_coords[centroid], all_coords[j]], m:1, self.schema_info['field_name_prenetwork']:None, "postnetwork":None, "dist":d}
                                    connector_edges_to_insert[edge][pn] = 1
                                    connector_edges_to_insert[edge][fft_name]= d/1.34
                                else:
                                    connector_edges_to_insert[edge][pn] = 1
                                    connector_edges_to_insert[edge][fft_name]= d/1.34
                                    connector_edges_to_insert[edge][m]= 1
        
        arcpy.AddMessage(f"Saving connectors to {self.fc_ways_output}")
        weight_field_keys = [v for _,v in self.weight_fields.items()]
        with arcpy.da.InsertCursor(str(self.fc_ways_output), ["SHAPE@", self.schema_info["field_name_way_id"], self.schema_info["field_name_oneway"],
                                                               self.schema_info["field_name_highway"], self.schema_info["field_name_from_id"],
                                                               self.schema_info["field_name_to_id"], self.schema_info['field_name_prenetwork'], 
                                                               self.schema_info['field_name_postnetwork'], 
                                                               self.schema_info["field_name_length_meters"]] + modes + weight_field_keys) as ic:
            lineids = []
            for k,v in connector_edges_to_insert.items():
                points = []
                for x in v["ids"]:
                    points.append(arcpy.Point(x[0], x[1]))
                rid = random_id.create_random_id("CONN", lineids)
                polyline = arcpy.Polyline(arcpy.Array(points))
                fft_weights = [v[x] if x in v else None for x in weight_field_keys ]
                modevalues = [v[x] if x in v else 0 for x in modes ]
                
                ic.insertRow([polyline, rid, "yes", "centroid_connector", k[0], k[1], v[self.schema_info['field_name_prenetwork']], v["postnetwork"], v["dist"]] + modevalues + fft_weights)
      
        with arcpy.da.InsertCursor(str(self.fc_dt_temp), ["SHAPE@", self.schema_info["field_name_origin_name"], "mode", "network"]) as ic:
            for t in tri.simplices:
                if any(x in self.origin_centroid_indices for x in t):
                    print
                    points = []#[ for x in t]
                    GEOID = None
                    for x in t:
                        points.append(arcpy.Point(all_coords[x][0], all_coords[x][1]))
                        if x in self.index_to_origin_id:
                            GEOID = self.index_to_origin_id[x]
                    polyline = arcpy.Polyline(arcpy.Array(points))
                    ic.insertRow([polyline, GEOID, m, pn])
        self.remove_from_water()
        self.remove_from_highway()

    def create_connectors_wd(self, distance_from_border: float, orig_type: str):
        """
        Create connectors from each census centroid to every network node within a buffer
        of the census block polygon (buffered by distance_from_border in Feet).
        Minimal changes from prior implementation: buffer polygons once and use them
        to select nearby nodes.
        """
        # modes (keep same order as schema references used elsewhere)
        modes = [
            self.schema_info["field_name_vehicle_mode"],
            self.schema_info["field_name_truck_mode"],
            self.schema_info["field_name_pedestrian_mode"],
            self.schema_info["field_name_bicycle_mode"],
            self.schema_info["field_name_p_pedestrian_mode"],
            self.schema_info["field_name_p_bicycle_mode"]
        ]

        junctions = self.scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]
        nodes_fc = str(junctions)

        arcpy.AddMessage("Creating census centroid to nearby network node connectors (block polygon buffer)")

        # Prepare census centroid geometries (unchanged)
        origin_centroid_points = []
        for origin_id, coord in self.origin_centroids.items():
            pt = arcpy.Point(coord[0], coord[1])
            point_geom = arcpy.PointGeometry(pt, self.utmsr)
            origin_centroid_points.append((origin_id, point_geom))

        # Build FFT field names exactly for the modes being used (preserve order)
        try:
            weight_field_keys = [self.weight_fields[m] for m in modes]
        except KeyError as e:
            raise KeyError(f"Mode '{e.args[0]}' not found in self.weight_fields mapping.") from e

        # Build out_fields in the exact order we'll insert values
        out_fields = [
            "SHAPE@",
            self.schema_info["field_name_way_id"],
            self.schema_info["field_name_oneway"],
            self.schema_info["field_name_highway"],
            self.schema_info["field_name_from_id"],
            self.schema_info["field_name_to_id"],
            self.schema_info['field_name_prenetwork'],
            self.schema_info['field_name_postnetwork'],
            self.schema_info["field_name_length_meters"]
        ] + modes + weight_field_keys

        arcpy.AddMessage(f"Output fields: {out_fields}")

        # Validate output fields exist on target feature class (ignore SHAPE@)
        fc_field_names = [f.name for f in arcpy.ListFields(str(self.fc_ways_output))]
        missing = [f for f in out_fields if f != "SHAPE@" and f not in fc_field_names]
        if missing:
            raise Exception(f"Missing required fields on {self.fc_ways_output}: {missing}")

        # 1. Use the explicitly selected origin type to choose the buffer geometry
        census_fc = str(self.scenario_fgdb / self.schema_info["fc_name_census_block_prj"])
        custom_poly_fc = str(self.scenario_fgdb / self.schema_info["fc_name_custom_origin_polygons"])
        
        #origins_fc is either polygons or points
        if orig_type == "Census Blocks" and arcpy.Exists(census_fc):
            origins_fc = census_fc
        elif orig_type == "Custom Polygons" and arcpy.Exists(custom_poly_fc):
            origins_fc = custom_poly_fc
        else:
            origins_fc = str(self.fc_nodes_output)

        # 2. Buffer the origins to subset network nodes that fall within defined radius of all origins to improve spatial join performance
        buffered_origins_fc = "in_memory/buffered_blocks"
        if arcpy.Exists(buffered_origins_fc):
            arcpy.Delete_management(buffered_origins_fc)
        arcpy.Buffer_analysis(
            in_features=str(origins_fc), 
            out_feature_class=buffered_origins_fc, 
            buffer_distance_or_field=f"{distance_from_border} Feet",
            line_side="FULL", line_end_type="ROUND", dissolve_option="NONE", method="GEODESIC"
        )

        #Creating copy of network nodes for subset selection that get passed to spatial join
        nodes_layer_subset = "nodes_lyr_for_selection"
        if arcpy.Exists(nodes_layer_subset):
            arcpy.Delete_management(nodes_layer_subset)
        arcpy.MakeFeatureLayer_management(str(nodes_fc), nodes_layer_subset)

        # Select nodes that intersect the buffers directly from the FC
        arcpy.SelectLayerByLocation_management(nodes_layer_subset, "INTERSECT", buffered_origins_fc, selection_type="NEW_SELECTION")
        
        # Filter out motorway network nodes because these are not valid direct access points to the network from origins
        motorway_field = self.schema_info.get("field_name_motorway", "is_motorway")
        where_motorway = f"{motorway_field} = 0 OR {motorway_field} IS NULL"
        arcpy.SelectLayerByAttribute_management(nodes_layer_subset, "SUBSET_SELECTION", where_motorway)

        # 4. Spatial join subset network nodes to buffered origins
        nodes_origins_joined = "in_memory/nodes_spatial_join"
        if arcpy.Exists(nodes_origins_joined):
            arcpy.Delete_management(nodes_origins_joined)
        arcpy.analysis.SpatialJoin(
            target_features=nodes_layer_subset,
            join_features=buffered_origins_fc,
            out_feature_class=nodes_origins_joined,
            join_operation="JOIN_ONE_TO_MANY",
            join_type="KEEP_ALL",
            match_option="INTERSECT"
        )

        lineids = []
        # origin_name_field = self.schema_info["field_name_origin_name"]
        
        # # Helper to force identical string formatting ('06037', '30063...', etc.)
        # def sanitize(v):
        #     return str(v).split('.')[0].lstrip('0').strip() if v else ""
            
        # oid_to_geoid = {row[0]: sanitize(row[1]) for row in arcpy.da.SearchCursor(buffered_origins_fc, [oid_field, origin_name_field])}

        # join_fid_field = [f.name for f in arcpy.ListFields(nodes_origins_joined) if "JOIN_FID" in f.name.upper()][0]

        search_fields = ["SHAPE@XY", self.schema_info["field_name_node_id"]] + modes + [
            self.schema_info['field_name_prenetwork'],
            self.schema_info['field_name_postnetwork'], self.schema_info['field_name_origin_id']
        ]
        
        dt_rows = []
        nodes_origins_information = [row[:] for row in arcpy.da.SearchCursor(nodes_origins_joined, search_fields)]
        
        # # 8. Build dictionary with exact string keys from Python memory
        # node_information_dict = {sanitize(x[0]): [] for x in origin_centroid_points}
        
        # for row in raw_node_information:
        #     origin_id = row[-1] # The JOIN_FID is the last field requested
        #     if origin_id in oid_to_geoid:
        #         # Map the FID back to the true geoid string!
        #         true_geoid = oid_to_geoid[join_fid]
        #         if true_geoid in node_information_dict:
        #             node_information_dict[true_geoid].append(row)

        origin_id_field_idx = search_fields.index(self.schema_info['field_name_origin_id'])
        node_information_dict = {x[0]:[] for x in origin_centroid_points}
        for row in nodes_origins_information:
            if row[origin_id_field_idx] in node_information_dict:
                node_information_dict[row[origin_id_field_idx]].append(row)

        outputRows = []
        for origin_id, centroid_geom in origin_centroid_points:
            if origin_id in node_information_dict:
                selected = node_information_dict[origin_id]
                if len(selected) > 0:               
                    for row in selected:
                        node_xy = row[0]
                        node_id = row[1]

                        # Build connector polyline
                        pts = [
                            arcpy.Point(centroid_geom.centroid.X, centroid_geom.centroid.Y),
                            arcpy.Point(node_xy[0], node_xy[1])
                        ]
                        connector_geom = arcpy.Polyline(arcpy.Array(pts), self.utmsr)

                        # Distance between centroid & node (units in spatial ref)
                        #dist = arcpy.PointGeometry(arcpy.Point(node_xy[0], node_xy[1]), self.utmsr).distanceTo(centroid_geom)
                        dist = 0 #dist set at zero for centroids connectors

                        # Mode flags from the node row (indices 2..)
                        mode_values = []
                        for i in range(len(modes)):
                            val = row[2 + i]
                            mode_values.append(val if val is not None else 0)

                        # FFT weights: one per mode (match weight_field_keys)
                        fft_weights = [(dist / 1.34) for _ in modes]

                        # prenet/postnet values come after modes in the search cursor
                        prenet_idx = 2 + len(modes)
                        postnet_idx = prenet_idx + 1
                        prenet_value = row[prenet_idx] if prenet_idx < len(row) else None
                        postnet_value = row[postnet_idx] if postnet_idx < len(row) else None

                        rid = random_id.create_random_id("CONN", lineids)
                        lineids.append(rid)

                        # Values in the same order as out_fields
                        values = [
                            connector_geom,
                            rid,
                            "yes",                 # oneway
                            "centroid_connector",  # highway type
                            origin_id,            # from_id
                            node_id,               # to_id (network node id)
                            prenet_value,
                            postnet_value,
                            dist
                        ] + mode_values + fft_weights

                        # Sanity check before inserting
                        if len(values) != len(out_fields):
                            arcpy.AddError(f"Field/value length mismatch. fields={len(out_fields)} values={len(values)}")
                            arcpy.AddError(f"fields: {out_fields}")
                            arcpy.AddError(f"values: {values}")
                            raise Exception("Field/value length mismatch before insertRow")

                        outputRows.append(values)

                        mode_flags = []
                        for idx, mode_field in enumerate(modes):
                            val = mode_values[idx] if idx < len(mode_values) else 0
                            if val:

                                mode_flags.append(mode_field)
                        mode_value_for_dt = "|".join(mode_flags) if mode_flags else None

                        network_flags = []
                        if prenet_value:
                            network_flags.append("prenetwork")
                        if postnet_value:
                            network_flags.append("postnetwork")
                        network_value_for_dt = "|".join(network_flags) if network_flags else None

                        # Insert into the diagnostics/temp FC (fc_dt_temp)
                        dt_rows.append([connector_geom, origin_id, mode_value_for_dt, network_value_for_dt])
        with arcpy.da.InsertCursor(str(self.fc_ways_output), out_fields) as ic:
            for row in outputRows:
                ic.insertRow(row)
        if dt_rows:
            arcpy.AddMessage(f"Inserting {len(dt_rows)} rows into {self.fc_dt_temp}")
            with arcpy.da.InsertCursor(str(self.fc_dt_temp), ["SHAPE@", self.schema_info["field_name_origin_name"], "mode", "network"]) as ic_temp:
                for dt_row in dt_rows:
                    ic_temp.insertRow(dt_row)

        # cleanup
        if arcpy.Exists(str(buffered_origins_fc)):
            arcpy.Delete_management(str(buffered_origins_fc))
        if arcpy.Exists(str(nodes_layer_subset)):
            arcpy.Delete_management(str(nodes_layer_subset))
        if arcpy.Exists(str(nodes_origins_joined)):
            arcpy.Delete_management(str(nodes_origins_joined))

        arcpy.AddMessage("Finished creating connectors.")
        # remove any connectors that cross water
        self.remove_from_water()
        self.remove_from_highway()