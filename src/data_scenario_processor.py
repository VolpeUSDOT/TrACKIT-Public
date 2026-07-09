from pathlib import Path
import arcpy
from arcpy import metadata as md
from static_tools import helper_functions
import json
import yaml
from datetime import datetime
import os
from math import ceil
from scipy.spatial import KDTree
import numpy as np
import pandas as pd
from arcgis.features import GeoAccessor, GeoSeriesAccessor
from static_tools import random_id
from messenger import custMessenger
from messenger import custTypes
from managers import settingsManager
from managers import POICategoryManager
import copy
class scenario(settingsManager):
    """
    Create a new project scenario.

    Creates the following for a new scenario:
    - geodatabase
    - settings
    - schema
    - metadata
    - table
    - name
    - map
    - copy of OSM data, including contraflow ways for bicycle and pedestrian modes

    Parameters:
        - arcgisProject (ArcGISProjectobject): current project the toolbox is running in
        - projectFolder (Path): folder where the project data is written
        - projFGDB (Path): project file geodatabase where the processed OSM data is written
        - scenarioName (str): name of the scenario
        - bufferMiles (float): distance to create a subset of the OSM data, or None if using the whole dataset
        - scenarioModes (list): selection of mode(s) from settings mode_name_matching key values
        - scenarioLatitude (float): latitude of the project center
        - scenarioLongitude (float): longitude of the project center

    Effects:
        - Opens the scenario geodatabase and map

    Usage:
        Called by the class generate_scenario_networks.
        
    """



    def __init__(self, arcgisProject:arcpy.mp.ArcGISProject, projectFolder:Path, projFGDB:Path, scenarioName:str,
                 bufferMiles:float, scenarioModes:list, scenarioLatitude:float, scenarioLongitude:float,
                 scenarioCategories:list):
        """
        Builds a geodatabase for a scenario to make it easier for the user to edit a copy of the original OSM data.
        
        Args:
            - arcgisProject (ArcGISProjectobject): current project the toolbox is running in
            - projectFolder (Path): folder where the project data is written
            - projFGDB (Path): project file geodatabase where the processed OSM data is written
            - scenarioName (str): name of the scenario
            - bufferMiles (float): distance to create a subset of the OSM data, or None if using the whole dataset
            - scenarioModes (list): selection of mode(s) from settings mode_name_matching key values
            - scenarioLatitude (float): latitude of the project center
            - scenarioLongitude (float): longitude of the project center
        
        Returns:
            None
        """
        super().__init__(projectFolder, scenario_name = scenarioName)
        self.proj = arcgisProject
        self.scenario_modes = scenarioModes
        self.fields_to_remove_ways = self.schema_info["fields_to_remove"]
        self.scenario_name = scenarioName
        self.scenario_latitude = scenarioLatitude
        self.scenario_longitude = scenarioLongitude
        self.scenarios_existing = []
        self.scenario_folder = None
        self.scenario_fgdb = None
        self.buffer_miles = bufferMiles
        self.centroid = arcpy.PointGeometry(arcpy.Point(scenarioLongitude, scenarioLatitude), helper_functions.get_wgs84_sr())
        self.create_scenario_table()
        self.scenario_categories = scenarioCategories
        self.pcm = POICategoryManager(self.project_folder, self.project_fgdb)

    def set_metadata_attribution(self, fc_path:Path, title:str, tags:str, summary:str, desc:str):
        """
        Creates and populates metadata for the scenario.

        Args:
            - fc_path (Path): the path to which metadata will be assigned
            - title (str): metadata title
            - tags (str): metadata tags
            - summary (str): metadata summary
            - desc (str): metadata description

        Returns:
            None
        """
        new_md = md.Metadata()
        new_md.title = title
        new_md.tags = tags
        new_md.summary = summary
        new_md.description = desc
        new_md.credits = "OpenStreetMap® is open data, licensed under the Open Data Commons Open Database License (ODbL) by the OpenStreetMap Foundation (OSMF).\nYou are free to copy, distribute, transmit and adapt our data, as long as you credit OpenStreetMap and its contributors.\nIf you alter or build upon our data, you may distribute the result only under the same licence.\nThe full legal code explains your rights and responsibilities."
        tgt_item_md = md.Metadata(str(fc_path))
        if not tgt_item_md.isReadOnly:
            tgt_item_md.copy(new_md)
            tgt_item_md.save()



    def create_scenario_table(self):
        """
        Creates a table for the scenario if one does not exist.

        Args:
            None

        Returns:
            None
        """
        if arcpy.Exists(str(self.scenario_table)) is False:
            self.scenario_table = helper_functions.drop_add_fgdb_table(self.project_fgdb, self.scenario_table_name)

            for f in self.schema_info["scenario_table_fields"]:
                f["featureClass"] = self.scenario_table
                helper_functions.drop_add_field(**f)

    
    def add_new_scenario_to_table(self):
        """
        Adds a new entry to the scenario table for the created scenario.

        Args:
            Takes parameters from self

        Returns:
            None
        """
        
        scenario_fields = [f["field_name"] for f in self.schema_info["scenario_table_fields"]]
        with arcpy.da.InsertCursor(str(self.scenario_table), scenario_fields) as ic:
            mds = "|".join(self.scenario_modes)
            ic.insertRow([self.scenario_name,
                          self.buffer_miles,
                          datetime.now(),
                          self.scenario_fgdb.name,
                          mds, 0, None,
                          self.scenario_latitude,
                          self.scenario_longitude,
                          None, None,
                          "|".join(self.scenario_categories)])

    def build_poi_query(self):
        field_map = self.pcm.get_category_fields()
        clauses = []
        for k, v in field_map.items():
            if k in self.scenario_categories:
                clauses.append(f"({v} = 1)")
        return " OR ".join(clauses)

    def check_category_counts(self):
        field_map = self.pcm.get_category_fields()
        sedf_poi = pd.DataFrame.spatial.from_featureclass(location = str(self.project_fgdb / self.schema_info["fc_name_project_pois_nodes"]))
        for label, f in field_map.items():
            if label in self.scenario_categories:
                if sedf_poi[f].sum() == 0:
                    arcpy.AddWarning(f"{label} does not have any points of interest and will be removed from the Scenario POI dataset.")
                    self.scenario_categories.remove(label)
                elif sedf_poi[f].sum() <=10:
                    arcpy.AddWarning(f"{label} contains fewer than 10 points of interest.")
        if len(self.scenario_categories) == 0:
            arcpy.AddError("There are no POI categories with points.")
            raise Exception("There are no POI categories with points.")
        del sedf_poi
        return None
    

    def create_scenario_gdb(self):
        """
        Creates and opens a geodatabase for the scenario.

        Args:
            None

        Returns:
            None

        Effects:
            - Creates a geodatabase for the scenario
            - Copies features from the project into the scenario
            - Creates a domain for the action field
        """
        self.scenario_folder = self.project_folder / self.scenario_name
        self.scenario_folder.mkdir(exist_ok=True)
        self.scenario_fgdb = helper_functions.drop_add_fgdb(self.scenario_folder, f"{self.scenario_name}.gdb")
        fc_ways = None

        mode_to_field = {
                "Personal Vehicle": self.schema_info.get("field_name_vehicle_mode", "vehicle"),
                "Freight Truck": self.schema_info.get("field_name_truck_mode", "truck"),
                "Pedestrian": self.schema_info.get("field_name_pedestrian_mode", "pedestrian"),
                "Bicycle": self.schema_info.get("field_name_bicycle_mode", "bike"),
                "Low Stress Bicycle": self.schema_info.get("field_name_p_bicycle_mode", "p_bike"),
                "Low Stress Pedestrian": self.schema_info.get("field_name_p_pedestrian_mode", "p_walk")
            }
        wc_clauses = []
        gdb_path = str(self.project_fgdb)
        for ui_mode, fld_name in mode_to_field.items():
            if ui_mode in self.scenario_modes:
                # ensure proper delimiting for the workspace
                # TODO: arcpy documentation says AddFieldDelimiters is deprecated and no longer necessary in ArcGIS Pro;
                # check if this can run without this call
                #fld = arcpy.AddFieldDelimiters(gdb_path, fld_name)
                wc_clauses.append(f"{fld_name} >= 1")

        if len(wc_clauses) == 0:
            arcpy.AddError("No modes selected for the scenario, please select at least one mode.")
            return

        wc = " OR ".join(wc_clauses)
        arcpy.AddMessage(f"Where clause: {wc}")

        if self.buffer_miles is not None:
            epsg = [row[0] for row in arcpy.da.SearchCursor(str(self.project_fgdb/self.schema_info["fc_name_project_centroid"]), [self.schema_info["field_name_utm"]])][0]
            utmsr = arcpy.SpatialReference(epsg)
            buffer_dist = self.buffer_miles * 1609.34
            arcpy.AddMessage(f"Buffer distance {buffer_dist} meters")
            buffer_centroid = self.centroid.projectAs(utmsr).buffer(buffer_dist)
            arcpy.AddMessage("Copying subset of the OSM data")
            
            # 1. Filter WAYS spatially and by Mode (wc)
            selected_ways = arcpy.management.SelectLayerByLocation(str(self.project_fgdb / self.schema_info["fc_name_project_ways"]), "INTERSECT", buffer_centroid).getOutput(0)
            scenario_ways_path = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"])
            arcpy.analysis.Select(selected_ways, scenario_ways_path, wc)
            arcpy.management.DeleteField(scenario_ways_path, self.fields_to_remove_ways)

            selected_nodes = arcpy.management.SelectLayerByLocation(str(self.project_fgdb / self.schema_info["fc_name_project_nodes"]), "INTERSECT", buffer_centroid).getOutput(0)
            scenario_nodes_path = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_nodes"])
            arcpy.analysis.Select(selected_nodes, scenario_nodes_path, wc)
            
            # 3. Filter POIs
            selected_pois = arcpy.management.SelectLayerByLocation(str(self.project_fgdb / self.schema_info["fc_name_project_pois_nodes"]), "INTERSECT", buffer_centroid).getOutput(0)
            poi_wc = self.build_poi_query()
            selected_sub_pois = arcpy.management.SelectLayerByAttribute(selected_pois, 'SUBSET_SELECTION', poi_wc).getOutput(0)
            arcpy.management.CopyFeatures(selected_sub_pois, str(self.scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"]))       
        else:
            arcpy.AddMessage("Full copy of the OSM Data")
            
            # 1. Filter WAYS by Mode (wc)
            scenario_ways_path = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"])
            arcpy.analysis.Select(str(self.project_fgdb / self.schema_info["fc_name_project_ways"]), scenario_ways_path, wc)
            arcpy.management.DeleteField(scenario_ways_path, self.fields_to_remove_ways)
            
            # 2. Filter NODES purely by intersection with the valid WAYS
            scenario_nodes_path = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_nodes"])
            arcpy.analysis.Select(str(self.project_fgdb / self.schema_info["fc_name_project_nodes"]), scenario_nodes_path, wc)
            
            # 3. Copy POIs
            poi_wc = self.build_poi_query()
            selected_sub_pois = arcpy.management.SelectLayerByAttribute(str(self.project_fgdb / self.schema_info["fc_name_project_pois_nodes"]), 'NEW_SELECTION', poi_wc).getOutput(0)
            arcpy.management.CopyFeatures(selected_sub_pois, str(self.scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"]))

        # Now that the scenario network feature classes are generated, let's make sure we're pointing to them
        # to do some additional cleanup
        gdb = str(self.scenario_fgdb)
        fc_ways = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"])
        fc_nodes = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_nodes"])
        fc_pois = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"])

        if arcpy.Exists(fc_pois):
            all_cat_fields = self.pcm.get_category_fields()
            unselected_fields = [
                field_name for cat_name, field_name in all_cat_fields.items()
                if cat_name not in self.scenario_categories
            ]
            if unselected_fields:
                arcpy.AddMessage(f"Removing unselected POI category columns from Scenario POI feature class: {unselected_fields}")
                try:
                    arcpy.management.DeleteField(fc_pois, unselected_fields)
                except Exception as e:
                    arcpy.AddWarning(f"Could not drop unselected POI fields: {e}")

        # 1. Create a lookup dictionary mapping field names to their ArcPy types from the schema
        schema_types = {f["field_name"]: f["field_type"] for f in self.schema_info["integrate_ways_nodes_fc"]}
        
        # 2. Gather the exact fields we need to ensure exist
        mode_fields = [
            self.schema_info["field_name_vehicle_mode"], self.schema_info["field_name_truck_mode"],
            self.schema_info["field_name_pedestrian_mode"], self.schema_info["field_name_bicycle_mode"],
            self.schema_info["field_name_p_bicycle_mode"], self.schema_info["field_name_p_pedestrian_mode"]
        ]
        speed_fields = [
            self.schema_info["field_name_speed_vehicle"], self.schema_info["field_name_speed_truck"],
            self.schema_info["field_name_speed_pedestrian"], self.schema_info["field_name_speed_bicycle"],
            self.schema_info["field_name_speed_p_bike"]
        ]

        if arcpy.Exists(fc_ways):
            way_fields = [f.name for f in arcpy.ListFields(fc_ways)]
            for fld in mode_fields + speed_fields:
                if fld not in way_fields:
                    f_type = schema_types.get(fld, "DOUBLE") # Lookup exact type from schema
                    arcpy.AddMessage(f"Adding missing field '{fld}' to ways with value of 0.")
                    arcpy.management.AddField(fc_ways, fld, f_type)
                    arcpy.management.CalculateField(fc_ways, fld, 0)
                    
        if arcpy.Exists(fc_nodes):
            node_fields = [f.name for f in arcpy.ListFields(fc_nodes)]
            for fld in mode_fields:
                if fld not in node_fields:
                    f_type = schema_types.get(fld, "LONG") # Lookup exact type from schema
                    arcpy.AddMessage(f"Adding missing field '{fld}' to nodes with value of 0.")
                    arcpy.management.AddField(fc_nodes, fld, f_type)
                    arcpy.management.CalculateField(fc_nodes, fld, 0)

        # ENSURE MODAL FIELDS ARE BINARY VALUES FOR BOTH NETWORK WAYS AND NODES #

        mode_fields = [
            self.schema_info.get("field_name_vehicle_mode", "vehicle"),
            self.schema_info.get("field_name_truck_mode", "truck"),
            self.schema_info.get("field_name_pedestrian_mode", "pedestrian"),
            self.schema_info.get("field_name_bicycle_mode", "bike"),
            self.schema_info.get("field_name_p_bicycle_mode", "p_bike"),
            self.schema_info.get("field_name_p_pedestrian_mode", "p_walk")
        ]

        with arcpy.da.UpdateCursor(fc_ways, mode_fields) as cursor:
            for row in cursor:
                updated = False
                new_row = list(row)
                for i in range(len(new_row)):
                    # If value is 1 or more (like a '2'), cap it at 1. 
                    # If it's None or 0, ensure it is exactly 0.
                    current_val = new_row[i]
                    if current_val is not None and current_val >= 1:
                        if current_val != 1:
                            new_row[i] = 1
                            updated = True
                    elif current_val != 0:
                        new_row[i] = 0
                        updated = True
                if updated:
                    cursor.updateRow(new_row)
        
        with arcpy.da.UpdateCursor(fc_nodes, mode_fields) as cursor:
            for row in cursor:
                updated = False
                new_row = list(row)
                for i in range(len(new_row)):
                    current_val = new_row[i]
                    # Binary Check: if 1 or more, set to 1. If 0 or None, set to 0.
                    if current_val is not None and current_val >= 1:
                        if current_val != 1:
                            new_row[i] = 1
                            updated = True
                    elif current_val != 0:
                        new_row[i] = 0
                        updated = True
                
                if updated:
                    cursor.updateRow(new_row)

        # ADD ACTION FIELD TO SCENARIO NETWORK WAYS #

        helper_functions.drop_add_field(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"], self.schema_info["field_name_action"], "TEXT", field_alias="Scenario Action")

        #Assign domain values to action field
        try:
            action_field = self.schema_info["field_name_action"]
            action_domain_name = f"{action_field}_domain"
            coded_values = self.schema_info.get("action_options", [])

            # create or recreate domain (TEXT, CODED)
            try:
                arcpy.management.CreateDomain(gdb, action_domain_name, "Coded domain for action field", "TEXT", "CODED")
            except Exception:
                try:
                    arcpy.management.DeleteDomain(gdb, action_domain_name)
                    arcpy.management.CreateDomain(gdb, action_domain_name, "Coded domain for action field", "TEXT", "CODED")
                except Exception:
                    arcpy.AddWarning(f"Could not create domain {action_domain_name}")

            # populate domain
            for val in coded_values:
                try:
                    arcpy.management.AddCodedValueToDomain(gdb, action_domain_name, str(val), str(val))
                except Exception:
                    pass

            # assign domain to the action field on the main ways feature class (if exists)
            if arcpy.Exists(fc_ways):
                try:
                    arcpy.management.AssignDomainToField(fc_ways, action_field, action_domain_name)
                except Exception as e:
                    arcpy.AddWarning(f"Could not assign domain {action_domain_name} to {action_field}: {e}")
        except Exception as e:
            arcpy.AddWarning(f"Error creating domains from schema: {e}") 
    
        # ADD DOMAINS FOR BINARY FIELDS #

        #Binary fields list
        binary_fields = [
            self.schema_info["field_name_motorway"],
            self.schema_info["field_name_vehicle_mode"],
            self.schema_info["field_name_truck_mode"],
            self.schema_info["field_name_pedestrian_mode"],
            self.schema_info["field_name_bicycle_mode"],
            self.schema_info["field_name_p_bicycle_mode"],
            self.schema_info["field_name_p_pedestrian_mode"],
            self.schema_info["field_name_prenetwork"], # Note: only used in scenario network ways, NOT nodes
            self.schema_info["field_name_postnetwork"] # Note: only used in scenario network ways, NOT nodes
        ]
            
        binary_domain_name = "binary_domain"
        binary_domain_values = {0: "No", 1: "Yes"} # Code: Description

        try:
            # Delete the domain from the geodatabase if it already exists
            existing_domains = arcpy.Describe(gdb).domains
            if binary_domain_name in existing_domains:
                try:
                    arcpy.AddMessage(f"Removing old version of {binary_domain_name}")
                    arcpy.management.DeleteDomain(gdb, binary_domain_name)
                except Exception as e:
                    arcpy.AddWarning(f"Could not delete domain (it might be in use): {e}")
            
            # Define the binary domain on the geodatabase
            arcpy.management.CreateDomain(gdb, binary_domain_name, "Standard 0/1 Domain", "LONG", "CODED") 
              
            for code, desc_val in binary_domain_values.items():
                arcpy.management.AddCodedValueToDomain(gdb, binary_domain_name, code, desc_val)
                
            # Assign the binary domain to the relevant fields in scenario network ways and nodes feature classes
            if arcpy.Exists(fc_ways):
                for field in binary_fields:
                    try:
                        arcpy.management.AssignDomainToField(fc_ways, field, binary_domain_name)
                        arcpy.AddMessage(f"Successfully assigned {binary_domain_name} to {field} for ways")
                    except Exception as e:
                        arcpy.AddWarning(f"Could not assign domain to {field} for ways")
            else:
                arcpy.AddWarning(f"Feature class {fc_ways} not found. Skipping domain assignment.")

            if arcpy.Exists(fc_nodes):
                # Note: scenario network nodes doesn't have the pre/postnetwork fields, so we don't have to apply a domain for those
                for field in [x for x in binary_fields if x not in [self.schema_info["field_name_prenetwork"], self.schema_info["field_name_postnetwork"]]]:
                    try:
                        arcpy.management.AssignDomainToField(fc_nodes, field, binary_domain_name)
                        arcpy.AddMessage(f"Successfully assigned {binary_domain_name} to {field} for nodes")
                    except Exception as e:
                        arcpy.AddWarning(f"Could not assign domain to {field} for nodes")
            else:
                arcpy.AddWarning(f"Feature class {fc_nodes} not found. Skipping domain assignment.")

        except Exception as e:
            arcpy.AddWarning(f"Error creating binary domains: {e}")   
        
        # ADD DOMAINS FOR ONEWAY FIELD #

        try:
            oneway_field = self.schema_info["field_name_oneway"]
            oneway_domain_name = f"{oneway_field}_domain"
            oneway_domain_values = {"yes": "Yes", "no": "No"} # Code: Description

            # Define the domain on the geodatabase
            existing_domains = arcpy.Describe(gdb).domains
            if oneway_domain_name in existing_domains:
                try:
                    arcpy.AddMessage(f"Removing old version of {oneway_domain_name}")
                    arcpy.management.DeleteDomain(gdb, oneway_domain_name)
                except Exception as e:
                    arcpy.AddWarning(f"Could not delete domain (it might be in use): {e}")

            # Create new domain (TEXT, CODED)
            arcpy.management.CreateDomain(gdb, oneway_domain_name, "Coded domain for oneway field", "TEXT", "CODED")

            # Populate domain
            for code, desc_val in oneway_domain_values.items():
                try:
                    arcpy.management.AddCodedValueToDomain(gdb, oneway_domain_name, code, desc_val)
                except Exception:
                    pass

            # Assign domain to the oneway field on the main ways feature class (if exists)
            if arcpy.Exists(fc_ways):
                try:
                    arcpy.management.AssignDomainToField(fc_ways, oneway_field, oneway_domain_name)
                    arcpy.AddMessage(f"Successfully assigned {oneway_domain_name} to {oneway_field}")
                except Exception as e:
                    arcpy.AddWarning(f"Failed to assign domain {oneway_domain_name} to {oneway_field}: {e}")
            else:
                arcpy.AddWarning(f"Feature class {fc_ways} not found. Skipping domain assignment.")

        except Exception as e:
            arcpy.AddWarning(f"Error creating oneway domain: {e}")

        # Generate Custom Origin Templates inside the Scenario GDB
        arcpy.AddMessage("Creating custom origin templates within scenario geodatabase...")
        
        point_tmpl = str(self.scenario_fgdb / self.schema_info["fc_name_custom_origin_points"])
        helper_functions.drop_add_featureclass(self.scenario_fgdb, self.schema_info["fc_name_custom_origin_points"], "POINT", self.utmsr)
        for f in self.schema_info["origins_fields"]:
            f["featureClass"] = point_tmpl
            helper_functions.drop_add_field(**f)

        poly_tmpl = str(self.scenario_fgdb / self.schema_info["fc_name_custom_origin_polygons"])
        helper_functions.drop_add_featureclass(self.scenario_fgdb, self.schema_info["fc_name_custom_origin_polygons"], "POLYGON", self.utmsr)
        for f in self.schema_info["origins_fields"]:
            f["featureClass"] = poly_tmpl
            helper_functions.drop_add_field(**f)

        self.reverse_ped_bike()
        self.add_new_scenario_to_table()

    @staticmethod
    def create_working_map(proj, scenario_fgdb:Path, scenario_name:Path,
                            schema_info:dict, colors:dict, settings_info:dict):
        """
            creates a map for the scenario data within the arcgis pro project
            args:
                proj: arcgis pro project
                scenario_fgdb: path to the scenario geodatabase
                scenario_name: name of the scenario or name of the map
                schema_info: dictionary object from the yaml file
                colors: dictionary object from the colors.json file
                settings_info: dictionary object from the settings.json file

        """
        arcpy.AddMessage("Hard-resetting Map Layer Order and Templates...")
        
        # 1. Create the Map
        m = proj.createMap(scenario_name, "MAP")
        m.openView()
        # 2. Add Junctions (Nodes) FIRST - This puts them at the bottom
        nodes_fc = str(scenario_fgdb / schema_info["fc_name_scenario_nodes"])
        lyr_nodes_obj = arcpy.management.MakeFeatureLayer(nodes_fc, "Scenario Network Nodes").getOutput(0)
        lyr_nodes =  m.addLayer(lyr_nodes_obj, "TOP")[0]
        
        # 3. Add Ways (Lines) SECOND - This puts them on top of the nodes
        ways_fc = str(scenario_fgdb / schema_info["fc_name_scenario_ways"])
        lyr_ways_obj = arcpy.management.MakeFeatureLayer(ways_fc, "Scenario Network Ways").getOutput(0)
        lyr_ways = m.addLayer(lyr_ways_obj, "TOP")[0]

        existing_way_values = [row[0] for row in arcpy.da.SearchCursor(ways_fc, [schema_info["field_name_highway"]])]
        # 4. Grab fresh references
        #lyr_ways = m.listLayers("Ways")[0]
        #lyr_nodes = m.listLayers("Junctions")[0]

        # --- WAYS SYMBOLOGY & TEMPLATE FIX ---
        action_field = schema_info["field_name_action"]
        action_colors = colors.get("action_colors", {})
        
        cim_ways = lyr_ways.getDefinition('V3')
        cim_ways.autoGenerateFeatureTemplates = False
        # Construct the renderer as a dictionary to avoid AttributeError
        uv_classes = []
        for action, rgb in action_colors.items():
            if action == "EXISTING": continue
            uv_classes.append({
                "type": "CIMUniqueValueClass",
                "label": action,
                "values": [{"type": "CIMUniqueValue", "fieldValues": [action]}],
                "symbol": {
                    "type": "CIMSymbolReference",
                    "symbol": {
                        "type": "CIMLineSymbol",
                        "symbolLayers": [{
                            "type": "CIMSolidStroke",
                            "width": 3.0,
                            "color": {"type": "CIMRGBColor", "values": rgb if len(rgb)==4 else rgb+[100]}
                        }]
                    }
                }
            })

        cim_ways.renderer = {
            "type": "CIMUniqueValueRenderer",
            "fields": [action_field],
            "groups": [{"type": "CIMUniqueValueGroup", "classes": uv_classes}],
            "defaultLabel": "No Changes",
            "defaultSymbol": {
                "type": "CIMSymbolReference",
                "symbol": {
                    "type": "CIMLineSymbol",
                    "symbolLayers": [{
                        "type": "CIMSolidStroke",
                        "width": 1.0,
                        "color": {"type": "CIMRGBColor", "values": action_colors.get("EXISTING", [178, 178, 178, 85])}
                    }]
                }
            },
            "useDefaultSymbol": True
        }

        # Push the definition
        lyr_ways.setDefinition(cim_ways)

        # --- JUNCTIONS SYMBOLOGY ---
        cim_nodes = lyr_nodes.getDefinition('V3')
        cim_nodes.renderer = {
            "type": "CIMSimpleRenderer",
            "symbol": {
                "type": "CIMSymbolReference",
                "symbol": {
                    "type": "CIMPointSymbol",
                    "symbolLayers": [{
                        "type": "CIMVectorMarker",
                        "enable": True,
                        "size": 4.75, 
                        "markerGraphics": [{
                            "type": "CIMMarkerGraphic",
                            "geometry": {
                                # A 16-point ring creates a smooth, perfect circle
                                "rings": [[
                                    [0, 1], [0.38, 0.92], [0.71, 0.71], [0.92, 0.38],
                                    [1, 0], [0.92, -0.38], [0.71, -0.71], [0.38, -0.92],
                                    [0, -1], [-0.38, -0.92], [-0.71, -0.71], [-0.92, -0.38],
                                    [-1, 0], [-0.92, 0.38], [-0.71, 0.71], [-0.38, 0.92], [0, 1]
                                ]]
                            },
                            "symbol": {
                                "type": "CIMPolygonSymbol",
                                "symbolLayers": [
                                    {
                                        # DARK OUTLINE
                                        "type": "CIMSolidStroke",
                                        "enable": True,
                                        "capStyle": "Round",
                                        "joinStyle": "Round",
                                        "width": 0.6,
                                        "color": {"type": "CIMRGBColor", "values": [40, 40, 40, 70]} 
                                    },
                                    {
                                        # SEMI-TRANSPARENT FILL
                                        "type": "CIMSolidFill",
                                        "enable": True,
                                        "color": {"type": "CIMRGBColor", "values": [60, 60, 60, 60]}
                                    }
                                ]
                            }
                        }],
                        "frame": {"xmin": -1, "ymin": -1, "xmax": 1, "ymax": 1}
                    }]
                }
            }
        }
        lyr_nodes.setDefinition(cim_nodes)

        # Final View Update
        #m.openView()

        cim_ways = lyr_ways.getDefinition('V3')
        new_featureTemplates = []
        for ft in cim_ways.featureTemplates:
            if ft:
                if ft.name != "REMOVED":
                    new_featureTemplates.append(ft)
        arcpy.AddMessage(len(new_featureTemplates))
        #if len(new_featureTemplates) > 0:
        # arcpy.AddMessage("Creating Feature Templates")

        new_blank_ft = arcpy.cim.CIMVectorLayers.CIMRowTemplate()
        new_blank_ps = [
            schema_info['field_name_prenetwork'], 0,
            schema_info['field_name_postnetwork'], 1,
            action_field, 'NEW'
        ]
        new_blank_ft.defaultValues = {'type': 'PropertySet', 'propertySetItems': new_blank_ps}
        new_blank_ft.name = "NEW (Blank)"
        new_featureTemplates.append(new_blank_ft)

        footway_ft = None
        footway_ft = copy.copy(new_featureTemplates[0])
        footway_ps = [schema_info["field_name_highway"], 'footway',
                      schema_info["field_name_motorway"], 0,
                        schema_info['field_name_vehicle_mode'], 0,
                        schema_info['field_name_truck_mode'], 0,
                        schema_info['field_name_pedestrian_mode'], 1,
                        schema_info['field_name_bicycle_mode'], 1, 
                        schema_info['field_name_p_bicycle_mode'], 1,
                        schema_info['field_name_p_pedestrian_mode'], 1,
                        schema_info['field_name_p_bicycle_mode'], 1,
                        schema_info['field_name_speed_vehicle'], 0,
                        schema_info['field_name_speed_truck'], 0,
                        schema_info['field_name_speed_pedestrian'], 3, 
                        schema_info['field_name_speed_bicycle'],3,
                        schema_info['field_name_speed_p_bike'], 3,
                        schema_info['field_name_prenetwork'], 0,
                        schema_info['field_name_postnetwork'], 1,
                        action_field, 'NEW']
        footway_ft.defaultValues = {'type': 'PropertySet', 'propertySetItems': footway_ps}
        footway_ft.name = "NEW footway"
        new_featureTemplates.append(footway_ft)
        cycleway_ft = None
        cycleway_ft = arcpy.cim.CIMVectorLayers.CIMRowTemplate()
        cycleway_ps = [schema_info["field_name_highway"], 'cycleway',
                       schema_info["field_name_motorway"], 0,
                        schema_info['field_name_vehicle_mode'], 0,
                        schema_info['field_name_truck_mode'], 0,
                        schema_info['field_name_pedestrian_mode'], 1,
                        schema_info['field_name_bicycle_mode'], 1, 
                        schema_info['field_name_p_bicycle_mode'], 1,
                        schema_info['field_name_p_pedestrian_mode'], 1,
                        schema_info['field_name_p_bicycle_mode'], 1,
                        schema_info['field_name_speed_vehicle'], 0,
                        schema_info['field_name_speed_truck'], 0,
                        schema_info['field_name_speed_pedestrian'], 3, 
                        schema_info['field_name_speed_bicycle'],10,
                        schema_info['field_name_speed_p_bike'], 10,
                        schema_info['field_name_prenetwork'], 0,
                        schema_info['field_name_postnetwork'], 1,
                        action_field, 'NEW']
        cycleway_ft.defaultValues = {'type': 'PropertySet', 'propertySetItems':cycleway_ps}
        cycleway_ft.name = "NEW cycleway"
        new_featureTemplates.append(cycleway_ft)
        for speed, highways in settings_info["default_auto_speeds"].items():
            for tag in highways:
                # Filter out link types and service roads
                if "_link" in tag or tag == "service":
                    continue
                    
                if tag not in ["footway", "cycleway", "pedestrian", "path"]:
                    pedestrian_speed = 0
                    cycle_speed = 0
                    vehicle = 1
                    truck = 1
                    vehicle_speed = int(speed)
                    
                    if tag in ["tertiary", "tertiary_link", "unclassified"]:
                        truck_speed = 15
                    else:
                        truck_speed = int(float(speed) * 0.95) # 95% of vehicle speed
                        
                    motorway = 0
                    
                    # Initialize low stress default variables
                    p_bike_mode = 0
                    p_ped_mode = 0
                    speed_p_bike_val = 0
                    
                    if tag in settings_info["walkBikeAllowed"]:
                        pedestrian_mode = 1
                        cycle_mode = 1
                        pedestrian_speed = 3
                        cycle_speed = 10
                        
                    # Fix for residential and living_street low stress defaults
                    if tag in ["residential", "living_street"]:
                        p_bike_mode = 1
                        p_ped_mode = 1
                        speed_p_bike_val = 10
                        # Ensure standard walk/bike are also toggled on 
                        pedestrian_mode = 1
                        cycle_mode = 1
                        pedestrian_speed = 3
                        cycle_speed = 10

                    if tag in settings_info["setRoadToZero"]:
                        vehicle = 0
                        vehicle_speed = 0

                    if tag in settings_info["setTruckToZero"]:
                        truck = 0
                        truck_speed = 0
                        
                    if tag == "motorway":
                        motorway = 1
                        cycle_mode = 0
                        pedestrian_mode = 0
                        
                    temp_ft = arcpy.cim.CIMVectorLayers.CIMRowTemplate()
                    temp_ps = [schema_info["field_name_highway"], tag,
                               schema_info["field_name_motorway"], motorway,
                            schema_info['field_name_vehicle_mode'], vehicle,
                            schema_info['field_name_truck_mode'], truck,
                            schema_info['field_name_pedestrian_mode'], pedestrian_mode, 
                            schema_info['field_name_bicycle_mode'], cycle_mode, 
                            schema_info['field_name_p_bicycle_mode'], p_bike_mode,
                            schema_info['field_name_p_pedestrian_mode'], p_ped_mode,
                            schema_info['field_name_speed_vehicle'], vehicle_speed,
                            schema_info['field_name_speed_truck'], truck_speed,
                            schema_info['field_name_speed_pedestrian'], pedestrian_speed, 
                            schema_info['field_name_speed_bicycle'], cycle_speed,
                            schema_info['field_name_speed_p_bike'], speed_p_bike_val,
                            schema_info['field_name_prenetwork'], 0,
                            schema_info['field_name_postnetwork'], 1,
                            action_field, 'NEW']
                    temp_ft.defaultValues = {'type': 'PropertySet', 'propertySetItems':temp_ps}
                    temp_ft.name = f"NEW {tag}"
                    new_featureTemplates.append(temp_ft)

            cim_ways.featureTemplates = new_featureTemplates
            lyr_ways.setDefinition(cim_ways)
            
    def reverse_ped_bike(self):
        """
        Create reversed pedestrian and bicycle ways on one-way streets.


        By default, one-way street ways are one-way for all modes. However,
        pedestrians and cyclists should be able to travel in both directions
        when cars can only travel in one. This function uses the POLYLINE method
        to copy and reverse pedestrian and bicycle ways.

        Args:
            None
        
        Returns:
            None

        Effects:
            - Adds reversed pedestrian and bicycle ways to the scenario

        Usage:
            - Called during the creation of the scenario geodatabase
        """
        scenario_gdb = Path(self.scenario_fgdb)
        raw_links = str(scenario_gdb / self.schema_info["fc_name_scenario_ways"])
        field_objs = [f for f in arcpy.ListFields(str(raw_links)) if f.type not in ("OID", "Geometry")]
        field_names = [f.name for f in field_objs]
        read_fields = ["SHAPE@"] + field_names

        way_id_field_name = self.schema_info.get("field_name_way_id")
        p_ped_field_name = self.schema_info.get("field_name_p_pedestrian_mode")
        ped_field_name = self.schema_info.get("field_name_pedestrian_mode")
        bike_field_name = self.schema_info.get("field_name_bicycle_mode")
        p_bike_field_name = self.schema_info.get("field_name_p_bicycle_mode")
        vehicle_field_name = self.schema_info.get("field_name_vehicle_mode")
        truck_field_name = self.schema_info.get("field_name_truck_mode")
        speed_bike_field = self.schema_info.get("field_name_speed_bicycle")
        speed_p_bike_field = self.schema_info.get("field_name_speed_p_bike")
        reverse_bike_field = self.schema_info.get("field_name_reverse_bike_lane")
        reverse_ped_field = self.schema_info.get("field_name_reverse_ped_allowed")

        rev_bike_idx = field_names.index(reverse_bike_field)
        rev_ped_idx = field_names.index(reverse_ped_field)
        
        added_bike = 0

        insert_rev_bike_lanes = []
        with arcpy.da.SearchCursor(str(raw_links), read_fields) as src_cur:
            for rec in src_cur:
                try:
                    shape = rec[0]
                    attrs = list(rec[1:])  # aligns with field_names

                    if way_id_field_name in field_names:
                        try:
                            oi = field_names.index(way_id_field_name)
                            if attrs[oi] is not None and (str(attrs[oi]).startswith("REV_") or str(attrs[oi]).startswith("REVBIKE_")):
                                continue
                        except Exception:
                            pass

                    reverse_bike = False
                    if rev_bike_idx is not None and int(attrs[rev_bike_idx] or 0) >= 1:
                        reverse_bike = True
                    if not reverse_bike:
                        continue

                    parts = []
                    for part in shape:
                        pts = [p for p in part]
                        pts.reverse()
                        #arr = arcpy.Array([arcpy.Point(p.X, p.Y) for p in pts])
                        arr = arcpy.Array(pts)
                        parts.append(arr)
                    
                    if len(parts) == 1:
                        new_geom = arcpy.Polyline(parts[0], shape.spatialReference)
                    else:
                        new_geom = arcpy.Polyline(arcpy.Array(parts), shape.spatialReference)
                        
                    try:
                        if self.schema_info["field_name_from_id"] in field_names and self.schema_info["field_name_to_id"] in field_names:
                            fi = field_names.index(self.schema_info["field_name_from_id"])
                            ti = field_names.index(self.schema_info["field_name_to_id"])
                            attrs[fi], attrs[ti] = attrs[ti], attrs[fi]
                    except Exception:
                        pass

                    if vehicle_field_name  in field_names:
                        try:
                            vi = field_names.index(vehicle_field_name)
                            attrs[vi] = 0
                        except Exception:
                            pass
                    if truck_field_name in field_names:
                        try:
                            ti = field_names.index(truck_field_name)
                            attrs[ti] = 0
                        except Exception:
                            pass
                    if ped_field_name in field_names:
                        try:
                            pi = field_names.index(ped_field_name)
                            attrs[pi] = 0
                        except Exception:
                            pass

                    if p_ped_field_name in field_names:
                        try:
                            ppi = field_names.index(p_ped_field_name)
                            attrs[ppi] = 0
                        except Exception:
                            pass

                    if bike_field_name in field_names and speed_bike_field in field_names:
                        try:
                            bi = field_names.index(bike_field_name)
                            sbi = field_names.index(speed_bike_field)
                            if int(attrs[bi] or 0) == 1:
                                attrs[sbi] = float(self.settings_info.get("default_values", {}).get("speed_bike", 10.0))
                            else:
                                attrs[bi] = 0
                        except Exception:
                            pass

                    if p_bike_field_name in field_names and speed_p_bike_field in field_names:
                        try:
                            pbi = field_names.index(p_bike_field_name)
                            spbi = field_names.index(speed_p_bike_field)
                            if int(attrs[pbi] or 0) == 1:
                                attrs[spbi] = float(self.settings_info.get("default_values", {}).get("speed_p_bike", 10.0))
                            else:
                                attrs[pbi] = 0
                        except Exception:
                            pass

                    if way_id_field_name and way_id_field_name in field_names:
                        try:
                            oi = field_names.index(way_id_field_name)
                            if attrs[oi] is not None:
                                attrs[oi] = f"REVBIKE_{attrs[oi]}"
                        except Exception:
                            pass

                    insert_rev_bike_lanes.append([new_geom] + attrs)
                    added_bike += 1
                except Exception as e:
                    arcpy.AddWarning(f"Error creating reversed bike lane feature: {str(e)}")
                    continue
        with arcpy.da.InsertCursor(str(raw_links), read_fields) as rev_ic:
            for row in insert_rev_bike_lanes:
                rev_ic.insertRow(row)

        arcpy.AddMessage(f"Added {added_bike} reversed bike lane features.")

        insert_rev_ped_lanes = []
        added = 0
        with arcpy.da.SearchCursor(str(raw_links), read_fields) as src_cur:
            
            for rec in src_cur:
                try:
                    shape = rec[0]
                    attrs = list(rec[1:])  # aligns with field_names

                    # skip already-reversed features (avoid duplicates on rerun)
                    if way_id_field_name in field_names:
                        try:
                            orig_idx = field_names.index(way_id_field_name)
                            orig_val = attrs[orig_idx]
                            if orig_val is not None and (str(orig_val).startswith("REVBIKE_") or str(orig_val).startswith("REV_")):
                                continue
                        except Exception:
                            pass
                            
                    reverse_ped = False
                    if rev_ped_idx is not None and int(attrs[rev_ped_idx] or 0) == 1:
                        reverse_ped = True
                    if not reverse_ped:
                        continue

                    parts = []
                    for part in shape:
                        pts = [p for p in part]
                        pts.reverse()
                        arr = arcpy.Array([arcpy.Point(p.X, p.Y) for p in pts])
                        parts.append(arr)
                    
                    if len(parts) == 1:
                        new_shape = arcpy.Polyline(parts[0], shape.spatialReference)
                    else:
                        new_shape = arcpy.Polyline(arcpy.Array(parts), shape.spatialReference)

                    # swap from/to if present
                    try:
                        if self.schema_info["field_name_from_id"] in field_names and self.schema_info["field_name_to_id"] in field_names:
                            fi = field_names.index(self.schema_info["field_name_from_id"])
                            ti = field_names.index(self.schema_info["field_name_to_id"])
                            attrs[fi], attrs[ti] = attrs[ti], attrs[fi]
                    except Exception:
                        pass

                    if vehicle_field_name in field_names:
                        try:
                            vi = field_names.index(vehicle_field_name)
                            attrs[vi] = 0
                        except Exception:
                            pass
                    
                    if truck_field_name in field_names:
                        try:
                            ti = field_names.index(truck_field_name)
                            attrs[ti] = 0
                        except Exception:
                            pass

                    if bike_field_name in field_names:
                        try:
                            bi = field_names.index(bike_field_name)
                            attrs[bi] = 1
                        except Exception:
                            pass
                    
                    # set p_bike flag = 1
                    if p_bike_field_name in field_names and p_ped_field_name in field_names:
                            try:
                                pbi = field_names.index(p_bike_field_name)
                                ppi = field_names.index(p_ped_field_name)
                                if int(attrs[ppi] or 0) == 1:
                                    attrs[pbi] = 1
                                else:
                                    attrs[pbi] = 0  # or leave unchanged
                            except Exception:
                                pass
                    # set bike speed = 3 (if speed fields exist)
                    if speed_bike_field in field_names:
                        try:
                            sbi = field_names.index(speed_bike_field)
                            attrs[sbi] = int(self.settings_info.get("default_bike_in_pedestrian", 3))
                        except Exception:
                            pass
                    if speed_p_bike_field in field_names and p_ped_field_name in field_names:
                            try:
                                spbi = field_names.index(speed_p_bike_field)
                                ppi = field_names.index(p_ped_field_name)
                                if int(attrs[ppi] or 0) == 1:
                                    attrs[spbi] = int(self.settings_info.get("default_bike_in_pedestrian", 3))
                                else:
                                    attrs[spbi] = 0  # or existing value
                            except Exception:
                                pass

                    # suffix original id if present
                    if way_id_field_name in field_names:
                        try:
                            orig_idx = field_names.index(way_id_field_name)
                            if attrs[orig_idx] is not None:
                                attrs[orig_idx] = f"REV_{attrs[orig_idx]}"
                            else:
                                arcpy.AddMessage("Original ID field is None, cannot prefix with REV_.")
                        except Exception:
                            pass
                    insert_rev_ped_lanes.append([new_shape] + attrs)
                    
                    added += 1
                except Exception:
                    continue

        with arcpy.da.InsertCursor(str(raw_links), read_fields) as rev_ic:
            for row in insert_rev_ped_lanes:
                rev_ic.insertRow(row)
        
        arcpy.DeleteField_management(raw_links, self.schema_info.get("field_name_reverse_bike_lane"))
        arcpy.DeleteField_management(raw_links, self.schema_info.get("field_name_reverse_ped_allowed"))
        arcpy.AddMessage(f"Duplicated {added} reversed ways for oneway+pedestrian condition.")


class integrate_scenario(settingsManager):
    def __init__(self, projectFolder:Path, projFGDB:Path, scenarioName:str):
        """
            OSM pois processor inherits from processor class. Run separate_osm_data() first then build_data()
            Args:
                projectFolder (Path): folder where the project data is written.
                osmFile (Path): OSM XML file to process.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                process_OSM_ways object
        """
        super().__init__(projectFolder, scenarioName)

        self.project_fgdb = projFGDB
        self.scenario_name = scenarioName
        self.scenario_folder = self.project_folder / self.scenario_name
        self.scenario_fgdb = self.scenario_folder / f"{self.scenario_name}.gdb"
        self.fc_ways_output = None
        self.fc_nodes_output = None
        self.epsilon = float(self.settings_info["matching_tolerance_meters"])

        self.reportTxt = None

        self.fields_for_integrate = self.schema_info["fields_to_integrate"]


    def create_reporting_document(self):
        """
        
        Creates a text file with a date that logs errors
        Args:
            None
        Returns:
            None
        """
        self.reportTxt = open(self.scenario_folder / f"integrate_{self.scenario_name}_{datetime.now().strftime('%Y_%m_%d')}.txt", "w")
    def write_report_line(self, value, pointObj = None, classValue = None, silent=False):
        """

        Create a message in ArcGIS dialogue to note errors. Also add content to the error log created in the step above.
        Args:
            value: if value begins with X, it notes an error
        Returns:
            - Calls arcpy.AddMessage(value) to show a message in ArcGIS warning a user about something.
        """
        if silent is False:
            arcpy.AddMessage(value)
			
        if self.reportTxt:
            self.reportTxt.write(value + "\n")
			
        if pointObj is not None:
            error = 0
            if value[0] == 'X':
                error = 1
            self.point_checks_list.append([pointObj, error, value, classValue])

    def field_check_and_nulls(self, inputNetwork:str=None):
        """

        Looks through a series of required fields for integration, and alerts the user if any are missing.

        Args:
            inputNetwork: input feature class to validate its existence
        Returns:
            "X - (something) missing Field - name" if an item is missing.
        
        """
        self.write_report_line(f"Checking fields:")        
        input_fields = [f.name for f in arcpy.ListFields(inputNetwork)]
        missingf = []
        for f in self.fields_for_integrate:
            if f not in input_fields:
                self.write_report_line(f"X - {inputNetwork} missing Field - {f}.")
                missingf.append(f)
        #if len(missingf) == 0:
        #    self.write_report_line(f"O - {inputNetwork} has all required fields.")

        for mf in missingf:
            self.fields_for_integrate.remove(mf)
 
        # with arcpy.da.SearchCursor(inputNetwork, ["OID@"] + self.fields_for_integrate) as sc:
        #     for row in sc:
        #         for i, fn in enumerate(self.fields_for_integrate):
        #             if row[i+1] is None:
        #                 self.write_report_line(f"X - {inputNetwork} Field {f} contains a possible bad value at ObjectID {row[0]}.")

    def check_and_populate_nulls(self, inputNetwork):
        
        arcpy.AddMessage("Checking for and auto-populating missing speeds and modes based on highway tags...")

        # 1. Prepare speed and mode field lists
        existing_fields = [f.name for f in arcpy.ListFields(inputNetwork)]
        
        all_speed_fields = [
            self.schema_info["field_name_speed_vehicle"],
            self.schema_info["field_name_speed_truck"],
            self.schema_info["field_name_speed_bicycle"],
            self.schema_info["field_name_speed_p_bike"],
            self.schema_info["field_name_speed_pedestrian"]
        ]
        all_mode_fields = [
            self.schema_info["field_name_vehicle_mode"],
            self.schema_info["field_name_truck_mode"],
            self.schema_info["field_name_pedestrian_mode"],
            self.schema_info["field_name_bicycle_mode"],
            self.schema_info["field_name_p_bicycle_mode"],
            self.schema_info["field_name_p_pedestrian_mode"]
        ]
        highway_field = self.schema_info["field_name_highway"]
        way_id_field = self.schema_info["field_name_way_id"]
        speed_fields = [f for f in all_speed_fields if f in existing_fields]
        mode_fields = [f for f in all_mode_fields if f in existing_fields]
        
        # 2. Prepare speed and mode default dictionaries
        auto_speeds = {h: float(speed) for speed, highways in self.settings_info["default_auto_speeds"].items() for h in highways}
        bike_speeds = {h: float(speed) for speed, highways in self.settings_info["default_bike_speeds"].items() for h in highways}
        default_values = self.settings_info["default_values"]
        
        pedestrian_allowed = set(self.settings_info["walkBikeAllowed"] + self.settings_info["walkAllowed"] + self.settings_info["walkAllowedNoSidewalkTag"])
        bike_allowed = set(self.settings_info["walkBikeAllowed"] + self.settings_info["bikeAllowed"] + self.settings_info["bikeAlwaysFriendly"]+["steps"])
        vehicle_forbidden = set(self.settings_info["setRoadToZero"])
        truck_forbidden = set(self.settings_info["setTruckToZero"] + self.settings_info["setRoadToZero"])
        p_bike_allowed = set(self.settings_info["walkBikeAllowed"] + self.settings_info["bikeAlwaysFriendly"])
        p_pedestrian_allowed = set(self.settings_info["walkBikeAllowed"] + self.settings_info["walkAllowed"])

        # Build dynamic field list for cursor
        fields = ["OID@", way_id_field, highway_field] + speed_fields + mode_fields
        way_id_idx = 1
        hw_idx = 2
        data_start_idx = 3 # Where speeds/modes start in the row
        
        bad_no_highway = []
        bad_unmapped_highway = []

        # 3. Update and Validate
        with arcpy.da.UpdateCursor(inputNetwork, fields) as cursor:
            for row in cursor:
                row_list = list(row)
                oid = row_list[0]
                way_id = str(row_list[way_id_idx]) if row_list[way_id_idx] else "Unknown"
                highway = row_list[hw_idx]
                if highway is not None and str(highway).strip() == "":
                    highway = None
                updated = False
                
                is_unmapped = highway is not None and highway not in auto_speeds and highway not in pedestrian_allowed
                if is_unmapped:
                    arcpy.AddWarning(f"OID {oid} (Way ID: {way_id}) has unrecognized highway tag '{highway}'. Skipping auto-populate.")
                
                # 2. Attempt to populate nulls if highway exists AND is recognized
                if highway is not None and not is_unmapped:
                    # Populate speeds if they are None using highway tag
                    for i, field in enumerate(speed_fields, start=data_start_idx):
                        if row_list[i] is None or row_list[i] == 0:
                            if field == self.schema_info["field_name_speed_vehicle"]: 
                                row_list[i] = auto_speeds.get(highway, default_values["speed_vehicle"])
                            elif field == self.schema_info["field_name_speed_truck"]: 
                                base_v_speed = auto_speeds.get(highway, default_values["speed_vehicle"])
                                row_list[i] = 15.0 if highway in ["tertiary", "tertiary_link", "unclassified"] else (base_v_speed * 0.95)
                            elif field == self.schema_info["field_name_speed_bicycle"]: 
                                row_list[i] = bike_speeds.get(highway, default_values["speed_bike"])
                            elif field == self.schema_info["field_name_speed_p_bike"]: 
                                row_list[i] = bike_speeds.get(highway, default_values["speed_bike"])
                            elif field == self.schema_info["field_name_speed_pedestrian"]: 
                                row_list[i] = default_values["speed_pedestrian"]
                            updated = True
                    
                    # Populate modes if they are None
                    mode_start = data_start_idx + len(speed_fields)
                    for j, field in enumerate(mode_fields, start=mode_start):
                        if row_list[j] is None:
                            if field == self.schema_info["field_name_vehicle_mode"]: row_list[j] = 0 if highway in vehicle_forbidden else 1
                            elif field == self.schema_info["field_name_truck_mode"]: row_list[j] = 0 if highway in truck_forbidden else 1
                            elif field == self.schema_info["field_name_pedestrian_mode"]: row_list[j] = 1 if highway in pedestrian_allowed else 0
                            elif field == self.schema_info["field_name_bicycle_mode"]: row_list[j] = 1 if highway in bike_allowed else 0
                            elif field == self.schema_info["field_name_p_bicycle_mode"]: row_list[j] = 1 if highway in p_bike_allowed else 0
                            elif field == self.schema_info["field_name_p_pedestrian_mode"]: row_list[j] = 1 if highway in p_pedestrian_allowed else 0
                            updated = True

                    for m_fld, s_fld in [
                    (self.schema_info["field_name_vehicle_mode"], self.schema_info["field_name_speed_vehicle"]),
                    (self.schema_info["field_name_truck_mode"], self.schema_info["field_name_speed_truck"]),
                    (self.schema_info["field_name_pedestrian_mode"], self.schema_info["field_name_speed_pedestrian"]),
                    (self.schema_info["field_name_bicycle_mode"], self.schema_info["field_name_speed_bicycle"]),
                    (self.schema_info["field_name_p_bicycle_mode"], self.schema_info["field_name_speed_p_bike"]),
                    (self.schema_info["field_name_p_pedestrian_mode"], self.schema_info["field_name_speed_pedestrian"])
                    ]:
                        if m_fld in fields and s_fld in fields:
                            m_val = row_list[fields.index(m_fld)]
                            s_val = row_list[fields.index(s_fld)]
                            if m_val is not None and m_val >= 1 and s_val == 0:
                                arcpy.AddWarning(f"OID {oid}: '{m_fld}' is active but speed is 0.")

                # 3. Error Check
                if highway is None or any(val is None for val in row_list[data_start_idx:]):
                    feature_label = f"OID {oid} (Way ID: {way_id})"
                    if highway is None:
                        bad_no_highway.append(feature_label)
                    else:
                        bad_unmapped_highway.append(f"{feature_label} [Tag: {highway}]")
                elif updated:
                    # Only save back to the Geodatabase if we actually changed something
                    cursor.updateRow(row_list)

        if bad_no_highway or bad_unmapped_highway:
            error_msgs = ["Integration failed. Could not auto-populate missing speed or mode data:"]
            
            if bad_no_highway:
                error_msgs.append(f"\nMissing speed or mode data and missing 'highway' tag:")
                error_msgs.append(f"-> {', '.join(bad_no_highway)}")
                
            if bad_unmapped_highway:
                error_msgs.append(f"\nMissing speed or mode data and unrecognized 'highway' tag:")
                error_msgs.append(f"-> {', '.join(bad_unmapped_highway)}")
                
            full_error = "\n".join(error_msgs)
            self.messages.send_message(full_error)
            arcpy.AddError(full_error)
            raise arcpy.ExecuteError

    
    def integrate_network(self, inputNetwork:str=None):
        self.point_checks_list = []
        #if self.reportTxt is None:
        #    self.create_reporting_document()
        if inputNetwork is None:
            inputNetwork = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"])
        self.check_and_populate_nulls(inputNetwork)
        
        fc = str(self.scenario_fgdb / self.schema_info["fc_name_scenario_ways"])

        action_fld = self.schema_info["field_name_action"]
        pre_fld = self.schema_info["field_name_prenetwork"]
        post_fld = self.schema_info["field_name_postnetwork"]
        
        arcpy.AddMessage("Validating network flags based on Scenario Action.")
        
        with arcpy.da.UpdateCursor(inputNetwork, ["OID@", action_fld, pre_fld, post_fld]) as cursor:
            for row in cursor:
                oid, action, pre, post = row
                updated = False
                
                # Case 1: REMOVED Logic
                if action == "REMOVED":
                    if pre != 1:
                        pre = 1
                        updated = True
                        arcpy.AddWarning(f"OID {oid}: Action set to REMOVED but prenetwork was 0. Changed to 1.")
                    if post != 0:
                        post = 0
                        updated = True
                        arcpy.AddWarning(f"OID {oid}: Action set to REMOVED but postnetwork was 1. Changed to 0.")
                
                # Case 2: NEW Logic
                elif action == "NEW":
                    if pre != 0:
                        pre = 0
                        updated = True
                        arcpy.AddWarning(f"OID {oid}: Action set to NEW but prenetwork was 1. Changed to 0.")
                    if post != 1:
                        post = 1
                        updated = True
                        arcpy.AddWarning(f"OID {oid}: Action set to NEW but postnetwork was 0. Changed to 1.")
                
                if updated:
                    row[2], row[3] = pre, post
                    cursor.updateRow(row)

        # Re-check for remaining NULLs (original logic)
        with arcpy.da.SearchCursor(fc, [pre_fld, post_fld]) as cursor:
            for row in cursor:
                if row[0] is None or row[1] is None:
                    arcpy.AddError("Data integrity error: Found at least one feature with NULL value in prenetwork or postnetwork field.")
        
        arcpy.AddMessage("Finding changes.")

        workspace = arcpy.Describe(inputNetwork).path
        action_field_del = arcpy.AddFieldDelimiters(workspace, self.schema_info["field_name_action"])
        id_field_del = arcpy.AddFieldDelimiters(workspace, self.schema_info["field_name_way_id"])

        arcpy.AddMessage("Exporting project changes for reporting maps...")
        changes_out_fc = str(self.scenario_fgdb / "scenario_project_changes")
        
        if arcpy.Exists(changes_out_fc):
            arcpy.Delete_management(changes_out_fc)
            
        changes_where = f"{action_field_del} IN ('NEW', 'UPDATED', 'REMOVED')"
        try:
            arcpy.Select_analysis(inputNetwork, changes_out_fc, changes_where) # Select changed features to a new feature class for reporting
        except Exception as e:
            arcpy.AddWarning(f"Could not export project changes for maps: {e}")

        where_id_change = f"({action_field_del} = 'UPDATED' OR {id_field_del} IS NULL)"
        where_changed = f"{action_field_del} = 'NEW'"
        where_unchanged = f"{action_field_del} <> 'NEW' OR {action_field_del} IS NULL"


        #Get existing link ids to keep them unique when creating new ids
        existing_link_ids = []
        with arcpy.da.SearchCursor(inputNetwork, [self.schema_info["field_name_way_id"]]) as sc:
            for row in sc:
                if row[0]:
                    existing_link_ids.append(row[0])

        #Assign a unique id to the new lines
        with arcpy.da.UpdateCursor(inputNetwork, [self.schema_info["field_name_way_id"]], where_id_change) as uc:
            for row in uc:
                row[0] = random_id.create_random_id("NEW", existing_link_ids)
                existing_link_ids.append(row[0])
                uc.updateRow(row)
        #changed_links ACTION = 'NEW'
        changed_links = arcpy.MakeFeatureLayer_management(inputNetwork, "Changed Links", where_changed).getOutput(0)
        #connected_links lines within 50 meters of the new links
        #connected_links = arcpy.SelectLayerByLocation_management(inputNetwork, "WITHIN_A_DISTANCE", changed_links, "50 Meters", "NEW_SELECTION").getOutput(0)
        #connected_links lines that intersect any other lines
        connected_links = arcpy.SelectLayerByLocation_management(inputNetwork, "INTERSECT", changed_links, selection_type="NEW_SELECTION").getOutput(0)
        
        #update changed_links to be a new feature class, setting this to be in memory for faster processing and then not needing to delete it later
        changed_links = arcpy.CopyFeatures_management(connected_links, f"memory//{self.schema_info['fc_name_changed']}").getOutput(0)
        #unchanged_links are the links that are not updated
        unchanged_links = arcpy.SelectLayerByAttribute_management(inputNetwork, "NEW_SELECTION", where_unchanged).getOutput(0)
        unchanged_links = arcpy.SelectLayerByLocation_management(unchanged_links, "ARE_IDENTICAL_TO", changed_links, selection_type='REMOVE_FROM_SELECTION').getOutput(0)

        #write out the unchanged links to the new fc_ways_output featureclass
        arcpy.Append_management(unchanged_links, str(self.fc_ways_output), "NO_TEST")

        #number of links that ar changed
        changed_count = int(arcpy.GetCount_management(changed_links).getOutput(0))
        
        # --- START OF STRUCTURAL FIX ---
        if changed_count == 0:
            arcpy.AddMessage("No changed links found. Skipping integration of changed features.")
            self.field_check_and_nulls(changed_links)
            arcpy.AddMessage("Feature Lines with changes: 0")
        
        else:
            self.field_check_and_nulls(changed_links)
            action_field = self.schema_info["field_name_action"]
            new_action_val = 'NEW'
            new_oids = set()

            #Get the set of unique object ids and their action
            with arcpy.da.SearchCursor(changed_links, ["OID@", action_field]) as sc:
                for oid, action in sc:
                    if action == new_action_val:
                        new_oids.add(oid)
            #Get the set of features that were changed
            changed_features = {}
            with arcpy.da.SearchCursor(changed_links, ["OID@", "SHAPE@"] + self.fields_for_integrate) as sc:
                for row in sc:
                    changed_features[row[0]] = {"shape": row[1]}
                    for i, fn in enumerate(self.fields_for_integrate):
                        changed_features[row[0]][fn] = row[i+2]

            self.write_report_line(f"Feature Lines to be processed for possible changes: {len(changed_features)}")
            
            counts = {}
            for _,v in changed_features.items():
                if v[self.schema_info["field_name_highway"]] in counts:
                    counts[v[self.schema_info["field_name_highway"]]] += 1
                else:
                    counts[v[self.schema_info["field_name_highway"]]] = 1

            self.write_report_line("Types of Features being processed:")
            for k,v in counts.items():
                self.write_report_line(f"{v} of highway type {k}")

            #Get the junctions at are 100 meters of the changed features
            near_nodes = arcpy.SelectLayerByLocation_management(str(self.fc_nodes_output), "WITHIN_A_DISTANCE", changed_links, "100 Meters", "NEW_SELECTION").getOutput(0)
            #Get the coordinates of those junctions
            existing_nodes_coords = [(row[0][0], row[0][1]) for row in arcpy.da.SearchCursor(near_nodes, ["SHAPE@XY"])]
            #Get their data and the mode to confirm matching junctions have the same mode
            modes_check = [self.schema_info["field_name_vehicle_mode"], self.schema_info["field_name_truck_mode"], self.schema_info["field_name_bicycle_mode"], self.schema_info["field_name_pedestrian_mode"]]
            existing_nodes_data = [row[0:] for row in arcpy.da.SearchCursor(near_nodes, [self.schema_info["field_name_node_id"]] + modes_check)]
            #Create KD tree of the junctions
            node_tree = KDTree(np.array(existing_nodes_coords))

            #Get the coordinates of the lines to create a kdtree to find vertex matches
            all_line_coords = []
            all_line_coords_oid = []
            for k, v in changed_features.items():
                for part in v["shape"]:
                    for pnt in part:
                        all_line_coords.append((pnt.X, pnt.Y))
                        all_line_coords_oid.append(k)


            #This steps looks for any vertex that intersects with two or more vertices
            #If this is the case split the changed lines at the vertex
            if len(all_line_coords) > 0:
                all_line_coords_oid = np.array(all_line_coords_oid)
                all_line_coords = np.array(all_line_coords)
                line_tree = KDTree(all_line_coords)
                new_shapes = {k:[] for k,_ in changed_features.items()}

                self.write_report_line(f"Splitting lines at shared vertices.")
                
                new_split_lines = []
                
                for k,v in changed_features.items():
                    newpnts = []
                    #Get the coordinates for the current change feature
                    coords = all_line_coords[all_line_coords_oid==k]
                    #Get the index of the coordinates of current change feature
                    coords_indices = np.where(all_line_coords_oid==k)[0]
                    start_line = 0
                    for i, xy in zip(coords_indices, coords):
                        if start_line == 0:
                            newpnts.append(arcpy.Point(xy[0], xy[1]))
                            start_line = 1
                        elif np.all(xy == coords[-1]):
                                newpnts.append(arcpy.Point(xy[0], xy[1]))
                                arr = arcpy.Array(newpnts) 
                                new_shapes[k].append(arcpy.Polyline(arr, self.utmsr))
                        else:
                            dd, ii = line_tree.query(xy, k=5)
                            
                            idx_count = 1
                            for idx, d in zip(ii, dd):
                                if idx not in coords_indices:
                                    if d <= self.epsilon:
                                        neighbor_oid = all_line_coords_oid[idx]
                                        if k in new_oids or neighbor_oid in new_oids:
                                            idx_count += 1
                                            self.write_report_line(f"O - Topological match found for feature {k} with neighbor {neighbor_oid}.", 
                                                                    arcpy.Point(xy[0], xy[1]), 
                                                                    "MATCHED - VERTEX")
                            if idx_count == 1:
                                newpnts.append(arcpy.Point(xy[0], xy[1]))
                            elif idx_count > 1:
                                self.write_report_line(f"O - Splitting feature {k} at point {xy[0]}, {xy[1]}.", arcpy.Point(xy[0], xy[1]), "SPLIT VERTEX: INTEGRATION")
                                newpnts.append(arcpy.Point(xy[0], xy[1]))
                                arr = arcpy.Array(newpnts) 
                                new_shapes[k].append(arcpy.Polyline(arr, self.utmsr))
                                newpnts = [arcpy.Point(xy[0], xy[1])]
                del line_tree 
                #insert these lines into a temporary feature class
                with arcpy.da.InsertCursor(str(self.temp_poly), ["SHAPE@"]) as ic:
                    for k,v in new_shapes.items():
                        for l in v:
                            ic.insertRow([l])

                new_junctions_coords = []
                new_junctions_ids = []
                new_node_tree = None
                nodes_to_insert = {}
                selection_junctions = []
                link_id_index = self.fields_for_integrate.index(self.schema_info["field_name_way_id"])
                for k,v in changed_features.items():
                    if v[self.schema_info["field_name_postnetwork"]] == 0:
                        #self.write_report_line(f"O - The feature {k} is not part of the modified network. Keeping from and to ids.")
                        values = [v[fn] for fn in self.fields_for_integrate]
                        new_split_lines.append([v["shape"]] + values)
                    else:
                        shapes = new_shapes[k]
                        for i, shp in enumerate(shapes):
                            values = [v[fn] for fn in self.fields_for_integrate]
                            new_id = random_id.create_random_id("POST", existing_link_ids)
                            values[link_id_index] = new_id
                            existing_link_ids.append(new_id)
                            fp = shp.firstPoint
                            lp = shp.lastPoint
                            for label, pnt in [("start", fp),("last", lp)]:
                                self.write_report_line(f"Point {pnt.X}, {pnt.Y} was searched.", arcpy.Point(pnt.X, pnt.Y), "SEARCHED", silent=True)
                                from_to_index = self.schema_info["field_name_from_id"] if label == "start" else self.schema_info["field_name_to_id"]
                                from_to_index = self.fields_for_integrate.index(from_to_index)
                                dd, ii = node_tree.query((pnt.X, pnt.Y), k=1)
                                if dd <= self.epsilon:
                                    exist_node = existing_nodes_data[ii]
                                    values[from_to_index] = exist_node[0]
                                    if k in new_oids:
                                        self.write_report_line(f"O - Topological match found for feature {k} with neighbor {exist_node[0]}.", 
                                                            arcpy.Point(pnt.X, pnt.Y), 
                                                            "MATCHED")
                                else:
                                    self.write_report_line(f"X - The {label} point of feature {k} does not correspond to an existing OSM junction.", pnt, "UNMATCHED")
                                    from_to_index = self.schema_info["field_name_from_id"] if label == "start" else self.schema_info["field_name_to_id"]
                                    from_to_index = self.fields_for_integrate.index(from_to_index)
                                    if new_node_tree is not None:
                                        ndd, nii = new_node_tree.query((pnt.X, pnt.Y), k=1)
                                        if ndd <= self.epsilon:
                                            values[from_to_index] = new_junctions_ids[nii]
                                        else:
                                            new_id = random_id.create_random_id("POST", new_junctions_ids)
                                            values[from_to_index] = new_id
                                            nodes_to_insert[new_id] = arcpy.PointGeometry(pnt, self.utmsr)
                                            selection_junctions.append(arcpy.PointGeometry(pnt, self.utmsr))
                                            self.write_report_line(f"+ - Adding {new_id} for  {label} point of feature {k}.", pnt, "NEW JUNCTION/NODE")
                                            new_junctions_coords.append((pnt.X, pnt.Y))
                                            new_junctions_ids.append(new_id)
                                            del new_node_tree
                                            new_node_tree = KDTree(np.array(new_junctions_coords))

                                    else:
                                        new_id = random_id.create_random_id("POST", new_junctions_ids)
                                        values[from_to_index] = new_id
                                        nodes_to_insert[new_id] = arcpy.PointGeometry(pnt, self.utmsr)
                                        selection_junctions.append(arcpy.PointGeometry(pnt, self.utmsr))
                                        self.write_report_line(f"+ - Adding {new_id} for  {label} point of feature {k}.", pnt, "NEW JUNCTION/NODE")
                                        new_junctions_coords.append((pnt.X, pnt.Y))
                                        new_junctions_ids.append(new_id)
                                        new_node_tree = KDTree(np.array(new_junctions_coords))

                            new_split_lines.append([shp] + values)
                if new_node_tree: del new_node_tree 

                with arcpy.da.InsertCursor(str(self.fc_nodes_output), ["SHAPE@", self.schema_info["field_name_node_id"]]) as ic:
                    for k,v in nodes_to_insert.items():
                        ic.insertRow([v, k])

                with arcpy.da.InsertCursor(str(self.fc_ways_output), ["SHAPE@"] + self.fields_for_integrate) as ic:
                    for v in new_split_lines:
                        try:
                            ic.insertRow(v)
                        except Exception as e:
                            arcpy.AddWarning(f"Failed to insert row. Error: {e}. Data: {str(v[1:])}")

                with arcpy.da.InsertCursor(str(self.point_checks), self.point_checks_fields) as ic:
                    for row in self.point_checks_list:
                        ic.insertRow(row)
                
                with arcpy.da.InsertCursor(str(self.temp_junctions), ["SHAPE@", self.schema_info["field_name_node_id"]]) as ic:
                    for k,v in nodes_to_insert.items():
                        ic.insertRow([v, k])

        # --- UNIVERSAL ATTRIBUTE UPDATE ---
        # This part now runs for EVERY scenario (Base or New Geometry)
        arcpy.AddMessage("Updating node attributes based on integrated links...")
        node_network_flags = {}
        node_highways = {}
        node_linkosmids = {}

        with arcpy.da.SearchCursor(str(self.fc_ways_output), [self.schema_info["field_name_from_id"], self.schema_info["field_name_to_id"], 
                                                              self.schema_info["field_name_prenetwork"], self.schema_info["field_name_postnetwork"], 
                                                              self.schema_info["field_name_motorway"], self.schema_info["field_name_vehicle_mode"], 
                                                              self.schema_info["field_name_truck_mode"],
                                                              self.schema_info["field_name_pedestrian_mode"], self.schema_info["field_name_bicycle_mode"],
                                                            self.schema_info["field_name_p_pedestrian_mode"], self.schema_info["field_name_p_bicycle_mode"], 
                                                            self.schema_info["field_name_highway"], self.schema_info["field_name_way_id"]]) as cursor:
            for from_osmid, to_osmid, pre, post, is_motorway, road, truck, walk, bike, p_walk, p_bike, highway, osmid in cursor:
                for node_id in [from_osmid, to_osmid]:
                    if node_id not in node_network_flags:
                        node_network_flags[node_id] = {self.schema_info["field_name_prenetwork"]: 0, self.schema_info["field_name_postnetwork"]: 0,
                                                        self.schema_info["field_name_motorway"]: 0, self.schema_info["field_name_count"]: 0, self.schema_info["field_name_vehicle_mode"]:0, self.schema_info["field_name_truck_mode"]:0, self.schema_info["field_name_pedestrian_mode"]:0, self.schema_info["field_name_bicycle_mode"]:0, self.schema_info["field_name_p_pedestrian_mode"]:0, self.schema_info["field_name_p_bicycle_mode"]:0}
                        node_highways[node_id] = []
                        node_linkosmids[node_id] = []
                    node_network_flags[node_id][self.schema_info["field_name_count"]] += 1
                    if pre is not None and pre > node_network_flags[node_id][self.schema_info["field_name_prenetwork"]]:
                        node_network_flags[node_id][self.schema_info["field_name_prenetwork"]] = pre
                    if post is not None and post > node_network_flags[node_id][self.schema_info["field_name_postnetwork"]]:
                        node_network_flags[node_id][self.schema_info["field_name_postnetwork"]] = post
                    if is_motorway is not None and is_motorway > node_network_flags[node_id][self.schema_info["field_name_motorway"]]:
                        node_network_flags[node_id][self.schema_info["field_name_motorway"]] = is_motorway
                    if road is not None and road >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_vehicle_mode"]] = 1
                    if truck is not None and truck >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_truck_mode"]] = 1
                    if walk is not None and walk >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_pedestrian_mode"]] = 1    
                    if bike is not None and bike >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_bicycle_mode"]] = 1
                    if p_walk is not None and p_walk >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_p_pedestrian_mode"]] = 1
                    if p_bike is not None and p_bike >= 1:
                        node_network_flags[node_id][self.schema_info["field_name_p_bicycle_mode"]] = 1
                    if highway:
                        node_highways[node_id].append(highway)
                    if osmid is not None:
                        node_linkosmids[node_id].append(str(osmid))

        arcpy.RepairGeometry_management(str(self.fc_ways_output), 'DELETE_NULL')
        with arcpy.da.UpdateCursor(str(self.fc_nodes_output), [self.schema_info["field_name_node_id"], self.schema_info["field_name_prenetwork"],
                                                               self.schema_info["field_name_postnetwork"], self.schema_info["field_name_motorway"],
                                                               self.schema_info["field_name_count"], self.schema_info["field_name_vehicle_mode"],
                                                               self.schema_info["field_name_truck_mode"],
                                                               self.schema_info["field_name_pedestrian_mode"], self.schema_info["field_name_bicycle_mode"],
                                                               self.schema_info["field_name_p_pedestrian_mode"], self.schema_info["field_name_p_bicycle_mode"],
                                                               self.schema_info["field_name_highway"],self.schema_info["field_name_link_origid"]]) as cursor:
            for row in cursor:
                node_id = row[0]
                if node_id in node_network_flags:
                    row[1] = node_network_flags[node_id][self.schema_info["field_name_prenetwork"]]
                    row[2] = node_network_flags[node_id][self.schema_info["field_name_postnetwork"]]
                    row[3] = node_network_flags[node_id][self.schema_info["field_name_motorway"]]
                    row[4] = node_network_flags[node_id][self.schema_info["field_name_count"]]
                    row[5] = node_network_flags[node_id][self.schema_info["field_name_vehicle_mode"]]
                    row[6] = node_network_flags[node_id][self.schema_info["field_name_truck_mode"]]
                    row[7] = node_network_flags[node_id][self.schema_info["field_name_pedestrian_mode"]]
                    row[8] = node_network_flags[node_id][self.schema_info["field_name_bicycle_mode"]]
                    row[9] = node_network_flags[node_id][self.schema_info["field_name_p_pedestrian_mode"]]
                    row[10] = node_network_flags[node_id][self.schema_info["field_name_p_bicycle_mode"]]
                    
                    highways_list = node_highways.get(node_id, [])
                    row[11] = "|".join(highways_list) if highways_list else None
                    linkosmid_list = node_linkosmids.get(node_id, [])
                    joined = "|".join(linkosmid_list) if linkosmid_list else None
                    if joined is not None and len(joined) > 100:
                        joined = joined[:100]
                    row[12] = joined

                else:
                    row[1] = 0
                    row[2] = 0
                    row[3] = 0
                    row[4] = 0
                    row[5] = 0
                    row[6] = 0
                    row[7] = 0
                    row[8] = 0
                    row[9] = 0
                    row[10] = 0
                    row[11] = None
                    row[12] = None
                cursor.updateRow(row)

        arcpy.AddMessage("Node attributes updated.")
        if self.reportTxt:
            self.reportTxt.close()
        try:
            arcpy.management.Delete(self.temp_junctions)
        except:
            pass

        try:
            arcpy.management.Delete(self.temp_poly)
        except:
            pass

        try:
            arcpy.management.Delete(changed_links)
        except:
            pass
    def calculate_fft(self):

        """
        Compute fft (free flow travel time) for each network segment across all modes

        Iterates through every feature in the fc_ways_output, calculating length in meters, and then computing 
        FFT for each mode (bicycle, pedestrian, vehicle, protected bike). FFT in seconds is 3600*length_m/1609.344*speed_mph

        Args:
            None

        Returns: 
            None

        """

        arcpy.AddMessage("Calculating FFT")
        fields = ["OID@", "SHAPE@", self.schema_info["field_name_length_meters"], self.schema_info["field_name_speed_bicycle"], 
                  self.schema_info["field_name_speed_pedestrian"], self.schema_info["field_name_speed_vehicle"], 
                  self.schema_info["field_name_speed_truck"], 
                  self.schema_info["field_name_speed_p_bike"], self.schema_info["field_name_fft_vehicle"], 
                  self.schema_info["field_name_fft_truck"], 
                  self.schema_info["field_name_fft_bike"], self.schema_info["field_name_fft_ped"], 
                  self.schema_info["field_name_fft_p_bike"]]
        outputDict = {}
        with arcpy.da.SearchCursor(str(self.fc_ways_output), fields) as sc:
            for row in sc:
                oid = row[0]
                outRow = list(row)
                if row[1] is not None:
                    outRow[2] = row[1].length
                    for m in self.schema_info["field_mode_prefix"]:
                        speed_index = fields.index(f"speed_{m}")
                        fft_index = fields.index(f"fft_{m}")
                        if row[speed_index] is None:
                            outRow[fft_index] = None
                            arcpy.AddWarning(f"Feature with OID {oid} has no speed for mode {m}, cannot calculate FFT.")
                        elif row[speed_index]> 0:
                            outRow[fft_index] = (3600 * row[1].length) / (1609.344 * row[speed_index]) #length = meters, maxspeed = mph
                        else:
                            outRow[fft_index] = None
                    outputDict[oid] = outRow
        with arcpy.da.UpdateCursor(str(self.fc_ways_output), fields) as uc:
            for row in uc:
                if row[0] in outputDict:
                    for i in range(2, len(fields)):
                        row[i] = outputDict[row[0]][i]
                    uc.updateRow(row)

    def set_symbology(self, lyr, symbolName, colorRGB = [255, 0, 0, 100], symbolSize = 8, angle=0):

        """
        Apply symbology.

        Args:
            lyr: layer that will be changed
            symbolName: name of the symbol to apply
            colorRGB: colors, in RGB
            symbolSize: size fo the symbol, with a default of 8
            angle: rotation angle of the symbol in degrees.

        Returns:
            None.

        """
        symbology = lyr.symbology

        symbology.renderer.symbol.applySymbolFromGallery(symbolName)
        # Example: Changing to a SimpleRenderer
        if hasattr(symbology, 'renderer'):
            #symbology.updateRenderer("SimpleRenderer")
            renderer = symbology.renderer
            renderer.symbol.color = {"RGB": colorRGB} # Red color with 100% opacity
            renderer.symbol.outlineColor = {"RGB": [0, 0, 0, 100]} # Black outline
            renderer.symbol.size = symbolSize
            renderer.symbol.angle = angle
        lyr.symbology = symbology

    def create_map_for_review(self, proj:arcpy.mp.ArcGISProject):

        """
        Build and display a map with integrated changes for reviewing within ArcGIS Pro

        The new map is called "Integrated Changes," and it adds feature layers for ways and junctions, and then 
        highlights specific vertex-related issues fro mthe report using custom symbols. 

        Args:
            proj (arcpy.mp.ArcGISProject): The ArcGIS Pro project object in which to create the review map.

        Returns:
            None.

        """

        arcpy.AddMessage("Creating review map.")
        m = proj.createMap("Integrated Changes", "MAP")
        lyr_ways = arcpy.management.MakeFeatureLayer(str(self.fc_ways_output), "New and Existing Ways").getOutput(0)
        m.addLayer(lyr_ways) 
        
        lyr_junctions = arcpy.management.MakeFeatureLayer(str(self.fc_nodes_output), "New and Existing Junctions").getOutput(0)
        lyr_junctions = m.addLayer(lyr_junctions)[0]
        lyr_junctions.visible = False
        
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "Split Vertices from Integration", "errorType = 'SPLIT VERTEX: INTEGRATION'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        self.set_symbology(_lyr, "Cross 1", [0,255,0,100], 10)
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "Split Vertices for Max Length", "errorType = 'SPLIT VERTEX: SPLIT FUNCTION'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        _lyr.visible = False
        self.set_symbology(_lyr, "Cross 2", [255,0,255,100])
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "New Vertex Matches Existing Junction", "errorType = 'MATCHED'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        self.set_symbology(_lyr, "Circle 1", [0,0,255,100])
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "Searched During Integration", "errorType = 'SEARCHED'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        _lyr.visible = False
        self.set_symbology(_lyr, "Square 1", [255,165,0,100])
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "Added New Junctions", "errorType = 'NEW JUNCTION/NODE'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        self.set_symbology(_lyr, "Triangle 1", [0,0,0,100])
        _lyr = arcpy.management.MakeFeatureLayer(str(self.scenario_fgdb / "integrate_vertex_report"), "Mode Mismatch", "errorType = 'MATCHED WRONG MODE'").getOutput(0)
        _lyr = m.addLayer(_lyr, "TOP")[0]
        self.set_symbology(_lyr, "Cross 1", [255,0,0,100], angle=45)
        # Add the newly created layer to the map
        
        m.openView()
        pass

    def create_output_fcs(self):

        """
        Prep output feature classes and fields for network integration.

        Creates or resets several feature classes within the scenario geodatabase: 
        - integrated line network feature class of ways
        - copied codes for junctions with additional network fields
        - temp feature classes for point checks, lines, junctions.
        Also adds required fields as needed in the schema.

        Args: 
            None

        Returns:
            None

        """

        self.fields_to_add = self.schema_info["integrate_ways_nodes_fc"]
        self.fc_ways_output = helper_functions.drop_add_featureclass(self.scenario_fgdb, self.schema_info["fc_name_integrated_network"], "POLYLINE", self.utmsr,"32_BIT") #oid must be 32 bit to be compatible with Network Analyst
        self.fc_nodes_output = arcpy.CopyFeatures_management(str(self.scenario_fgdb / self.schema_info["fc_name_scenario_nodes"]), str(self.scenario_fgdb / self.schema_info["fc_name_integrated_nodes"])).getOutput(0)
        helper_functions.drop_add_field(self.fc_nodes_output, self.schema_info["field_name_prenetwork"], "LONG")
        helper_functions.drop_add_field(self.fc_nodes_output, self.schema_info["field_name_postnetwork"], "LONG")
        
        for f in self.schema_info["integrate_ways_fc"]:
            f["featureClass"] = self.fc_ways_output
            helper_functions.drop_add_field(**f)
        
        for f in self.fields_to_add:
            f["featureClass"] = self.fc_ways_output
            helper_functions.drop_add_field(**f)

        self.point_checks = helper_functions.drop_add_featureclass(self.scenario_fgdb, "integrate_vertex_report", "POINT", self.utmsr,"32_BIT")
        self.temp_poly = helper_functions.drop_add_featureclass(Path("memory"), "integrate_temporary_polyline", "POLYLINE", self.utmsr,"32_BIT")
        self.temp_junctions = helper_functions.drop_add_featureclass(Path("memory"), "integrate_temporary_junctions", "POINT", self.utmsr,"32_BIT")
        helper_functions.drop_add_field(self.temp_junctions, self.schema_info["field_name_node_id"], "TEXT", field_length=200)
        self.point_checks_list = []
        chkfields = [{"featureClass":None,"field_name":"error","field_type":"LONG"},
        {"featureClass":None,"field_name":"desc","field_type":"TEXT", "field_length":500},
        {"featureClass":None,"field_name":"errorType","field_type":"TEXT", "field_length":100}]
        self.point_checks_fields = ["SHAPE@", "error", "desc", "errorType"]
        for f in chkfields:
            f["featureClass"] = self.point_checks
            helper_functions.drop_add_field(**f)
        
        #self.set_metadata_attribution(self.fc_ways_output, "Integrated Network Data", "Network, Segments", "Integrated Network with new segments. May contain OpenStreetMap data.", "Integrated Network with new segments. May contain OpenStreetMap data.")
        #self.set_metadata_attribution(self.fc_nodes_output, "Integrated Network Junction Data", "Network, Junctions", "Integrated Network with new segments. May contain OpenStreetMap data.", "Integrated Network with new segments. May contain OpenStreetMap data.")
    

    def get_segment_measures(self, coords:np.array, segment_length:float, minimum_segment_length:float=1):
        """ Coordinates are assumed meters"""

        #Calculate cumulative distances along the original line
        distances = np.linalg.norm(coords[1:] - coords[:-1], axis=1)
        cumulative_distances = np.concatenate(([0.0], np.cumsum(distances)))
        total_length = cumulative_distances[-1]
        if total_length <= segment_length:
            return np.array([]).reshape(0, 2) # Return empty array if no points needed


        target_distances = np.arange(0, total_length + 1e-9, segment_length)
        
        # Ensure the very last point exactly matches the end distance
        if target_distances[-1] != total_length:
            target_distances = np.append(target_distances, total_length)

        # 3. Identify and filter out distances that match original coordinates
        # We create a boolean mask to filter target_distances
        is_original_vertex_dist = np.isin(target_distances.round(decimals=9), 
                                        cumulative_distances.round(decimals=9))
        
        # Select only the target distances that are *not* original vertices
        distances_to_interpolate = target_distances[~is_original_vertex_dist]
        
        # If all points happen to fall exactly on original vertices, return nothing
        if distances_to_interpolate.size == 0:
            return np.array([]).reshape(0, 2)
        ordered_pos = list(distances_to_interpolate)
        if min(ordered_pos) != 0:
            ordered_pos = [0] + ordered_pos
        if max(ordered_pos) < total_length:
            if (total_length-max(ordered_pos)) < minimum_segment_length:
                ordered_pos[ordered_pos.index(max(ordered_pos))] = total_length
            else:
                ordered_pos.append(total_length)
        ordered_pos.sort()
        ordered_array = np.array([(ordered_pos[i-1], ordered_pos[i]) for i in range(1,len(ordered_pos))])
        # 4. Interpolate coordinates for only the necessary distances
        #new_x_coords = np.interp(distances_to_interpolate, cumulative_distances, coords[:, 0])
        #new_y_coords = np.interp(distances_to_interpolate, cumulative_distances, coords[:, 1])
        
        # Combine back into a 2D coordinate array
        #new_coords = np.vstack((new_x_coords, new_y_coords)).T
        
        return ordered_array


    def new_lines(self, geom:dict, positions:list):

        array = arcpy.Array()
        for path in geom.paths:
            for point_coords in path:
                array.add(arcpy.Point(point_coords[0], point_coords[1]))
        polyline = arcpy.Polyline(array, arcpy.SpatialReference(geom.spatialReference['wkid']))
        if positions is None:
            return [polyline]

        segments = []
        i = 0
        for position in positions:
            seg = polyline.segmentAlongLine(position[0], position[1])
            segments.append(seg)

        return segments

    def firstPoint(self, geom:arcpy.Polyline):
        #if "paths" in geom:
        #    firstCoords = geom["paths"][0][0]
        #    return {'x': firstCoords[0], 'y': firstCoords[1], 'spatialReference': {'wkid': geom['spatialReference']['wkid']}}
        if geom is not None:
            return geom.firstPoint
        else:
            return None
        
    def update_original(self, oldstr, newlist):
        oldstrlist = oldstr.split("|")
        oldstrlist += newlist
        oldstrlist = [x.replace("|", "") for x in oldstrlist]
        return "|".join(list(set(oldstrlist)))

    def split_and_reid_links(self, split_length:float):
        """
        Rewrite of split_and_reid_links:
        - preserves existing junction osmids (do not renumber),
        - only creates new junction osmids prefixed with "SPLIT_" for points added by splitting,
        - creates new split link osmids ensuring uniqueness across specified datasets,
        - writes new in-memory feature classes and replaces scenario FCs at the end.
        """

        scenario_gdb = Path(self.scenario_fgdb)
        raw_links = str(scenario_gdb / self.schema_info["fc_name_integrated_network"])
        raw_junctions = str(scenario_gdb / self.schema_info["fc_name_integrated_nodes"])
        self.point_checks_list = []
        
        if not arcpy.Exists(raw_links):
            raise RuntimeError(f"Input network not found: {raw_links}")

        way_id_field = self.schema_info["field_name_way_id"]
        orig_way_id_field =  self.schema_info["field_name_link_origid"]
        length_field = self.schema_info["field_name_length_meters"]
        drop_fields = []
        self.messages.send_message(f"Splitting lines longer than {split_length} meters")

        sedf_ways = pd.DataFrame.spatial.from_featureclass(location = raw_links)
        sedf_nodes = pd.DataFrame.spatial.from_featureclass(location = raw_junctions)
        
        sedf_ways[length_field] = sedf_ways.SHAPE.apply(lambda geom: geom.length)
        original_line_count = len(sedf_ways)
        original_junction_count = len(sedf_nodes)

        sedf_ways["coords"] = sedf_ways["SHAPE"].apply(lambda x: np.array(x["paths"][0]))
        drop_fields.append("coords")
        hw_field = self.schema_info["field_name_highway"]
        motorway_mask = False
        motorway_mask = sedf_ways[hw_field].isin(["motorway", "motorway_link"])
        mask_length = (sedf_ways[length_field]>split_length) & (~motorway_mask) #excluding motorways from splitting

        #get the split lengths along the line for only lines that are longer than the split_length
        ordered_pos = sedf_ways[mask_length]["coords"].apply(lambda x: self.get_segment_measures(x, split_length, 2))
        sedf_ways["positions"] = None
        sedf_ways.loc[mask_length, "positions"] = ordered_pos

        #get the new line segments for the splits
        #this should return as a list of dictionaries for spatially enabled data frame geometry (not the same as arcpy geometry)
        newSegments = sedf_ways[["SHAPE", "positions"]].apply(lambda x: self.new_lines(*x), axis=1)
        sedf_ways["splitsegments"] = None
        sedf_ways["splitsegments"] = newSegments
        drop_fields.append("splitsegments")
        sedf_ways["splitcount"] = sedf_ways["splitsegments"].apply(lambda x: len(x))
        drop_fields.append("splitcount")
        sedf_ways["OLD_ID"] = sedf_ways[way_id_field] #not needed but useful for testing
        drop_fields.append("OLD_ID")

        #duplicate the rows for each new split to copy the values from the original line
        duplicated = sedf_ways.reindex(sedf_ways.index.repeat(sedf_ways["splitcount"]))
        duplicated["splitlineindex"] = duplicated.groupby(level=0).cumcount()
        duplicated = duplicated.reset_index(drop=True)
        mask_is_split = duplicated["splitcount"] > 1
        mask_splitcount = duplicated["splitlineindex"] > 0
        #get the unique ids
        linkids = set(duplicated[way_id_field].to_list())
        #get the new way ids
        duplicated["newwayids"] = duplicated[way_id_field]
        for idx, row in duplicated[mask_is_split].iterrows():
            suffix = random_id.create_random_id("SPLITW", linkids, True)
            duplicated.at[idx, "newwayids"] = f"{row['OLD_ID']}_{suffix}"
        if len(duplicated[way_id_field].values) == original_line_count:
            arcpy.AddMessage(duplicated["positions"])
            raise Exception("Same count")
        #separate the lines from the list for use later
        duplicated["new_line"] = duplicated[["splitsegments", "splitlineindex"]].apply(lambda x: x[0][x[1]], axis=1)

        duplicated["new_to_node"] = None
        duplicated["new_from_node"] = None
        duplicated["new_to_node_id"] = duplicated["to_node_id"]
        duplicated["new_from_node_id"] = duplicated["from_node_id"]
        #only need the first point of the line for the new junctions first == last of the next segment
        duplicated.loc[mask_splitcount, "new_from_node"] = duplicated[mask_splitcount]["new_line"].apply(lambda x: self.firstPoint(x))

        for idx, row in duplicated[mask_splitcount].iterrows():
            pnt = row["new_from_node"]
            if pnt:
                # We use the old ID to help the user identify which original feature was broken up
                old_id = row.get("OLD_ID", "Unknown")
                self.write_report_line(
                    f"O - Long segment split for old feature {old_id} at point {pnt.X}, {pnt.Y}.", 
                    pnt, 
                    "SPLIT VERTEX: SPLIT FUNCTION",
                    silent=True
                )

        node_id_field = self.schema_info["field_name_node_id"]
        mask_new_junctions = duplicated["splitlineindex"] > 0
        junctionids = set(sedf_nodes[node_id_field].to_list())
        duplicated.loc[mask_new_junctions, "new_from_node_id"] = duplicated.loc[mask_new_junctions]["new_from_node_id"].apply(lambda x: f"{x}_{random_id.create_random_id('SPLITJ', junctionids, True)}")
        #for idx, row in duplicated.loc[mask_new_junctions].iterrows():
        #    suffix = random_id.create_random_id("SPLITJ", junctionids, True)
        #    orig_junc_id = row["new_from_node_id"]
        #    duplicated.at[idx, "new_from_node_id"] = f"{orig_junc_id}_{suffix}"

        #create the new junction ids
        duplicated["splitcount_m1"] = duplicated["splitcount"] - 1
        duplicated.loc[duplicated["splitlineindex"]!=duplicated["splitcount_m1"], "new_to_node_id"] = None
        duplicated.loc[duplicated["splitlineindex"]==duplicated["splitcount_m1"], "new_to_node"] = None
        duplicated["new_from_node_id"] = duplicated["new_from_node_id"].astype(str)
        duplicated["to_node_id"] = duplicated["to_node_id"].astype(str)
        #sort the values to make sure the segments are in the same order from start to end
        duplicated.sort_values(["OBJECTID","splitlineindex"], inplace=True)
        #shift the values up so that the from id becomes the to id
        shifted = duplicated.groupby("OBJECTID")["new_from_node_id"].shift(-1)
        mask_shift = (duplicated["splitcount_m1"] > 0) & (duplicated["splitlineindex"]!=duplicated["splitcount_m1"])
        duplicated.loc[mask_shift, "new_to_node_id"] = shifted[mask_shift]


        duplicated["SHAPE@"] = duplicated["new_line"]
        duplicated["from_node_id"] = duplicated["new_from_node_id"]
        duplicated["to_node_id"] = duplicated["new_to_node_id"]
        mask_shift = (duplicated["splitcount_m1"]>0) & (duplicated["splitlineindex"] >0)
        duplicated[way_id_field] = duplicated["newwayids"]

        self.messages.send_message("Line split complete.")

        self.messages.send_message("Fixing FFT.")
        #duplicated.spatial.set_geometry('SHAPE', inplace=True)
        duplicated[length_field] = duplicated["SHAPE@"].apply(lambda geom: geom.length)

        for m in self.schema_info["field_mode_prefix"]:
            speed_field = f"speed_{m}"
            fft_field = f"fft_{m}"
            duplicated.drop(fft_field, axis=1)
            duplicated[fft_field] = 0
            duplicated[fft_field] = np.where(duplicated[speed_field]>0, (3600 * duplicated[length_field]) / (1609.344 * duplicated[speed_field]), None) #length = meters, maxspeed = mph
            duplicated[fft_field] = duplicated[fft_field].astype('float') 

        
        out_ways_fc = str(scenario_gdb / self.schema_info["fc_name_integrated_network"])
        out_nodes_fc = str(scenario_gdb / self.schema_info["fc_name_integrated_nodes"])
        if arcpy.Exists(f"{out_ways_fc}_unsplit"):
            arcpy.Delete_management(f"{out_ways_fc}_unsplit")
        if arcpy.Exists(out_ways_fc):
            arcpy.Rename_management(out_ways_fc, out_ways_fc + "_unsplit")
        if arcpy.Exists(f"{out_nodes_fc }_unsplit"):
            arcpy.Delete_management(f"{out_nodes_fc }_unsplit")
        if arcpy.Exists(out_nodes_fc ):
            arcpy.Rename_management(out_nodes_fc , out_nodes_fc  + "_unsplit")
        if arcpy.Exists(str(out_ways_fc)):
            arcpy.Delete_management(str(out_ways_fc))

        self.messages.send_message("Saving new links.")
        self.messages.send_message("Creating new FeatureClass")
        template_fc = str(out_ways_fc + "_unsplit")
        tmpl_sr = None
        if arcpy.Exists(template_fc):
            tmpl_sr = arcpy.Describe(template_fc).spatialReference
        split_lines_fc = arcpy.CreateFeatureclass_management(
            out_path=str(scenario_gdb),
            out_name=self.schema_info["fc_name_integrated_network"],
            geometry_type="POLYLINE",
            template=template_fc,
            spatial_reference=tmpl_sr or self.utmsr
        ).getOutput(0)

        template_fc = str(out_nodes_fc + "_unsplit")
        tmpl_sr = None
        if arcpy.Exists(template_fc):
            tmpl_sr = arcpy.Describe(template_fc).spatialReference
        split_nodes_fc = arcpy.CreateFeatureclass_management(
            out_path=str(scenario_gdb),
            out_name=self.schema_info["fc_name_integrated_nodes"],
            geometry_type="POINT",
            template=template_fc,
            spatial_reference=tmpl_sr or self.utmsr
        ).getOutput(0)
        
        columns = list(sedf_ways.columns) + ["SHAPE@"]
        duplicated_output = duplicated[columns].drop(["OBJECTID", "coords","positions","splitsegments","splitcount","OLD_ID"], axis=1).copy()
        duplicated_output.replace([np.nan, pd.NaT, pd.NA], None, inplace=True)
        
        #duplicated_output.spatial.to_featureclass(out_ways_fc)
        #self.messages.send_message("Converting shapes.")
        #duplicated_output["SHAPE@"] = duplicated_output["SHAPE"].apply(lambda x: arcpy.AsShape(x, True))
        fields = duplicated_output.columns.to_list()
        fields.remove("SHAPE")
        self.messages.send_message("Inserting lines.")
        with arcpy.da.InsertCursor(split_lines_fc,
                                fields) as ic:
            for _, row in duplicated_output.iterrows():
                ic.insertRow([row[f] for f in fields])

        self.messages.send_message("Updating existing junctions with new link ids.")

        mask_update = (pd.isnull(duplicated["new_from_node"])) & (duplicated["splitcount_m1"]>0) & (duplicated["splitlineindex"]==duplicated["splitcount_m1"]) 
        #update_junctions = duplicated[mask_update].copy()
        update_way_ids = duplicated[mask_update][["newwayids", "new_to_node_id"]].groupby("new_to_node_id")["newwayids"].apply(list).to_dict()

        mask_update = sedf_nodes[node_id_field].isin(update_way_ids.keys())
        sedf_nodes.loc[mask_update, orig_way_id_field] = sedf_nodes[mask_update][[node_id_field, orig_way_id_field]].apply(lambda x: self.update_original(x[1], update_way_ids[x[0]]), axis=1)

        self.messages.send_message("Adding new junctions.")
        new_junctions = duplicated[~pd.isnull(duplicated["new_from_node"])].copy()
        new_junctions[node_id_field] = new_junctions["new_from_node_id"]
        new_junctions[orig_way_id_field] = new_junctions["newwayids"]
        new_junctions["count"] = 2
        new_junctions["SHAPE@"] = new_junctions["new_from_node"]
        sedf_nodes["SHAPE@"] = sedf_nodes["SHAPE"].apply(lambda x: arcpy.AsShape(x, True))
        new_junctions_output = pd.concat([sedf_nodes, new_junctions[sedf_nodes.columns]])
        new_junctions_output.replace([np.nan, pd.NaT, pd.NA], None, inplace=True)
        self.messages.send_message("Saving new junctions.")
        #new_junctions_output.spatial.to_featureclass(out_nodes_fc)
        fields = new_junctions_output.columns.to_list()
        fields.remove("SHAPE")
        self.messages.send_message("Inserting junctions.")
        with arcpy.da.InsertCursor(split_nodes_fc,
                                fields) as ic:
            for _, row in new_junctions_output.iterrows():
                ic.insertRow([row[f] for f in fields])
        self.messages.send_message(f"Original number of lines {original_line_count}.")
        self.messages.send_message(f"Original number of junctions {original_junction_count}.")
        self.messages.send_message(f"Split number of lines {len(duplicated[way_id_field].values)}.")
        self.messages.send_message(f"Split number of junctions {len(new_junctions_output[node_id_field].values)}.")
        
        self.messages.send_message("Saving length-based split points to report...")
        with arcpy.da.InsertCursor(str(self.point_checks), self.point_checks_fields) as ic:
            for row in self.point_checks_list:
                ic.insertRow(row)
        self.point_checks_list = []
    
        self.messages.send_message("Splitting complete.")

        if arcpy.Exists(f"{out_ways_fc}_unsplit"):
            arcpy.Delete_management(f"{out_ways_fc}_unsplit")
        if arcpy.Exists(f"{out_nodes_fc }_unsplit"):
            arcpy.Delete_management(f"{out_nodes_fc }_unsplit")

        return out_ways_fc, out_nodes_fc

