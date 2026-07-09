from pathlib import Path
import arcpy
from arcpy import metadata as md
from static_tools import helper_functions
import json
import yaml
import lxml.etree as ET
import pickle
from collections import Counter
from datetime import datetime
import os
import uuid
from scipy.spatial import KDTree
import numpy as np

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.gridspec as gridspec
import seaborn as sns
import re
from static_tools import random_id
from managers import settingsManager
from managers import POICategoryManager
from messenger import custMessenger

class processor(settingsManager):
    def __init__(self, projectFolder:Path, projFGDB:Path, messages:custMessenger=None):
        """
            Parent class for processing OpenStreetMap data
            Args:
                projectFolder (Path): folder where the project data is written.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                processor class object or child of the processor class.
        """
        super().__init__(projectFolder, messages)
        self.project_fgdb = projFGDB
        self.file_path = Path(__file__).parents[0]

    def separate_osm_data(self):
        pass

    def build_data(self):
        pass

    def set_metadata_attribution(self, fc_path:Path, title:str, tags:str, summary:str, desc:str, ):
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

class process_OSM_ways(processor):

    def __init__(self, projectFolder:Path, osmFile:Path, projFGDB:Path, messages:custMessenger=None):
        """
            OSM Ways processor inherits from processor class. Run separate_osm_data() first then build_data()
            Args:
                projectFolder (Path): folder where the project data is written.
                osmFile (Path): OSM XML file to process.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                process_OSM_ways object
        """
        super().__init__(projectFolder, projFGDB, messages)
        self.osm_file = osmFile
        self.ways_fields_to_add = None
        self.nodes_fields_to_add = None
        self.fc_ways = None
        self.fc_nodes = None

    def separate_osm_data(self):
        """
            Separates the OSM Node data and the Ways from the xml file for more efficient processing.
            Writes three files to the project folder: {project name}_nodes.data, {project name}_nodes_count.data, and {project name}_ways.data
            Args:
                None
            Returns:
                Files written to the project folder.
        """        
        out_file_root = self.project_folder.name.replace("_project","")
        nodes = {}
        # see https://lxml.de/tutorial.html for explanation of ET.iterparse
        arcpy.SetProgressor("step", "Processing nodes...",
            0, 100, 1)
        tracking_progress = 1
        for ev, n in ET.iterparse(str(self.osm_file), events=('end',), tag="node"):
            arcpy.SetProgressorPosition(tracking_progress)
            if n.attrib["id"] not in nodes:
                nodes[n.attrib["id"]] = (float(n.attrib["lat"]),float(n.attrib["lon"]))
            n.clear()
            if ev == 'end':
                n.clear()
            tracking_progress += 1
            if tracking_progress == 100:
                tracking_progress = 1
        arcpy.SetProgressorPosition(100)
        arcpy.ResetProgressor()
        arcpy.AddMessage("Saving nodes to project...")
        with open(self.project_folder  / f"{out_file_root}_nodes.data", 'wb') as outf:
            pickle.dump(nodes, outf, protocol=4)
        arcpy.SetProgressor("step", "Processing ways...",
            0, 100, 1)
        tracking_progress = 1
        ways = {}
        node_count = Counter()
        way_count = 1
        for ev, w in ET.iterparse(str(self.osm_file), events=('end',), tag="way"):
            arcpy.SetProgressorPosition(tracking_progress)
            if w.find('tag[@k="highway"]') is None:
                w.clear()
            else:
                nds = w.findall('nd')
                tags = w.findall('tag')
                values = {}
                values["nodes"] = [x.attrib["ref"] for x in nds]
                _ = [node_count.update([(x.attrib["ref"])]) for x in nds]
                values["tags"] = {x.attrib["k"]: x.attrib["v"] for x in tags}
                ways[w.attrib["id"]] = values
                del nds
                del tags
                w.clear()
            if ev == 'end':
                w.clear()
            tracking_progress += 1
            if tracking_progress == 100:
                tracking_progress = 1
        arcpy.SetProgressorPosition(100)
        arcpy.ResetProgressor()
        arcpy.AddMessage("Saving ways and node counts to project...")
        with open(self.project_folder / f"{out_file_root}_ways.data", 'wb') as outf:
            pickle.dump(ways, outf, protocol=4)
        with open(self.project_folder / f"{out_file_root}_nodes_count.data", 'wb') as outf:
            pickle.dump(node_count, outf, protocol=4)

    def build_data(self):
        """
            Reads the .data files created in separate_osm_data(). Creates two feature classes in the project geodatabase: osm_ways and osm_junctions.
            Classifies ways into segments used by vehicles (road = 1), bicycles (bike and p_bike = 1), and pedestrians (walk and p_walk = 1).
            Calculates the length of the segment (meters), and the free flow time based on default speeds for given OSM highway tags.

            Args:
                None
            Returns:
                Files written to the project file geodatabase
        """ 
        self.messages.send_message("Loading OSM data from xml files.")
        out_file_root = self.project_folder.name.replace("_project","")
        with open(self.project_folder / f"{out_file_root}_nodes.data", 'rb') as infile:
            nodes = pickle.load(infile)

        with open(self.project_folder / f"{out_file_root}_ways.data", 'rb') as infile:
            ways = pickle.load(infile)

        with open(self.project_folder / f"{out_file_root}_nodes_count.data", 'rb') as infile:
            node_count = pickle.load(infile)
        self.messages.send_message("Building feature classes to store ways and nodes.")
        self.build_fc()
        nodes_fields = ["SHAPE@"] + [v["field_name"] for v in self.nodes_fields_to_add]
        ways_fields = ["SHAPE@"] + [v["field_name"] for v in self.ways_fields_to_add]
        # default field values.  Default speeds are in mph
        # walk, bike are 0,1 fields indicating whether pedestrians or bicyclists are allowed
        # p_walk, p_bike are 0,1 fields indicating whether the links are walk or bike friendly 

        nodes_to_insert = {nid:{'SHAPE@':None, self.schema_info["field_name_node_id"]:None,
                            self.schema_info["field_name_count"]:0, self.schema_info["field_name_highway"]:"", 
                            self.schema_info["field_name_vehicle_mode"]:0, self.schema_info["field_name_truck_mode"]:0, self.schema_info["field_name_pedestrian_mode"]:0, 
                            self.schema_info["field_name_bicycle_mode"]:0, self.schema_info["field_name_p_pedestrian_mode"]:0, 
                            self.schema_info["field_name_p_bicycle_mode"]:0,
                            self.schema_info["field_name_link_origid"]:""} for nid in nodes.keys()}
        arcpy.SetProgressor("step", "Inserting segments into osm_ways...",
            0, len(ways.keys()), 1)
        
        with arcpy.da.InsertCursor(str(self.fc_ways), ways_fields) as ic:
            for wayid, v in ways.items():
                arcpy.SetProgressorPosition()
                p = 0
                #values that will be written to the fields
                values = {f:None for f in ways_fields}
                
                #tags associated with the way
                tags = v["tags"]

                #set the default values for the selected tags like speed
                for dk, dv in self.settings_info["default_values"].items():
                    values[dk] = dv

                #set the osmid to the way id
                values[self.schema_info["field_name_way_id"]] = wayid

                #set the highway value
                values[self.schema_info["field_name_highway"]] = tags["highway"]

                #handle the tags by pipe delimited
                values[self.schema_info["field_name_alltags"]] = "|".join(f"{k}:{v}" for k,v in tags.items())
                #length cutoff for ways with a lot of tags
                if len(values[self.schema_info["field_name_alltags"]]) >799:
                    values[self.schema_info["field_name_alltags"]] = values[self.schema_info["field_name_alltags"]][:790]

                if 'oneway' in tags:
                    values[self.schema_info["field_name_oneway"]] = tags['oneway']
                
                #get any of the tags to store as fields
                for k in ['maxspeed', 'surface', 'access', 'shoulder']:
                    if k in tags:
                        values[k] = tags[k]

                #custom check for maxspeed
                if "maxspeed:advisory" in tags:
                    values["maxspeed"] = tags["maxspeed:advisory"]
                
                #check for tiger classification
                #TODO doesn't seem to work
                if "tiger:cfcc" in tags:
                    values["cfcc"] = tags["tiger:cfcc"]


                #default road to 1
                values[self.schema_info["field_name_vehicle_mode"]] = 1
                values[self.schema_info["field_name_truck_mode"]] = 1
                
                #check for bikelane presence
                values[self.schema_info["field_name_bikelane"]] = 0
                for f in self.settings_info["doesItHaveaBikeLane"]:
                    if f in tags:
                        if tags[f] not in ['no', 'none']:
                            values[self.schema_info["field_name_bikelane"]] = 1
                            values[self.schema_info["field_name_bicycle_mode"]] = 1
                #check if the bikelane is protected
                #parsing osm tags to determnine the type of bicycle and pedestrian facilities
                values[self.schema_info["field_name_separated_bike"]] = 0
                for f in self.settings_info["bikeLaneProtected"]:
                    if f in tags:
                        if tags[f] not in ['no', 'none']:
                            values[self.schema_info["field_name_separated_bike"]] = 1
                            values[self.schema_info["field_name_bicycle_mode"]] = 1
                            values[self.schema_info["field_name_p_bicycle_mode"]] = 1
                #check for sidewalk presence
                values[self.schema_info["field_name_sidewalk"]] = 0
                for f in self.settings_info["doesItHaveaSidewalk"]:
                    if f in tags:
                        if tags[f] not in ['no', 'none']:
                            values[self.schema_info["field_name_sidewalk"]] = 1
                            values[self.schema_info["field_name_pedestrian_mode"]] = 1
                            values[self.schema_info["field_name_p_pedestrian_mode"]] = 1     
                #check if sidewalk is protected...   
                values[self.schema_info["field_name_separated_sidewalk"]] = 0
                for f in self.settings_info["doesItHaveProtectedSidewalk"]:
                    if f in tags:
                        if tags[f] not in ['no', 'none']:
                            values[self.schema_info["field_name_separated_sidewalk"]] = 1
                            values[self.schema_info["field_name_pedestrian_mode"]] = 1
                            values[self.schema_info["field_name_p_pedestrian_mode"]] = 1           

                #default speeds by facility type and mode (mph)
                #set the base speed for different highway tags
                for sk,sv in self.settings_info["default_auto_speeds"].items():
                    if tags["highway"] in sv:
                        values[self.schema_info["field_name_speed_vehicle"]] = int(sk)
                        break

                base_auto_speed = float(values[self.schema_info["field_name_speed_vehicle"]])

                hgv_tag_val = tags.get("hgv", "").lower()

                if hgv_tag_val in self.settings_info.get("hgv_local", []):
                    values[self.schema_info["field_name_speed_truck"]] = base_auto_speed * 0.5
                else:
                    values[self.schema_info["field_name_speed_truck"]] = base_auto_speed * 0.95


                #Apply a soft penalty to trucks for using more local roads
                if tags["highway"] in ["tertiary", "tertiary_link", "unclassified"]:
                    values[self.schema_info["field_name_speed_truck"]] = 15.0

                # on the following facilities, it is assumed that bikes are walked at low speed
                for sk,sv in self.settings_info["default_bike_speeds"].items():
                    if tags["highway"] in sv:
                        values[self.schema_info["field_name_speed_bicycle"]] = int(sk)
                        values[self.schema_info["field_name_speed_p_bike"]] = int(sk)
                        break
                
                #check walk 
                if tags["highway"] in self.settings_info["walkAllowedNoSidewalkTag"]:
                    values[self.schema_info["field_name_pedestrian_mode"]] = 1


                #check walk and bike highway tag
                if tags["highway"] in self.settings_info["walkBikeAllowed"]:
                    values[self.schema_info["field_name_pedestrian_mode"]] = 1
                    values[self.schema_info["field_name_p_pedestrian_mode"]] = 1
                    values[self.schema_info["field_name_bicycle_mode"]] = 1
                
                #check walk tags
                if tags["highway"] in self.settings_info["walkAllowed"]:
                    values[self.schema_info["field_name_pedestrian_mode"]] = 1
                    values[self.schema_info["field_name_p_pedestrian_mode"]] = 1
                
                #check walk tags
                if tags["highway"] in self.settings_info["bikeAllowed"]:
                    values[self.schema_info["field_name_bicycle_mode"]] = 1

                #check bike preferred\friendly
                if tags["highway"] in self.settings_info["bikeAlwaysFriendly"]:
                    values[self.schema_info["field_name_p_bicycle_mode"]] = 1

                #allow bikes for certain tags and there is a bikelane
                if tags["highway"] in self.settings_info["bikeAllowedIfBikeLane"] and values[self.schema_info["field_name_bikelane"]] == 1:
                    values[self.schema_info["field_name_bicycle_mode"]] = 1

                #allow p_bike for certain tags and there is a bikelane
                if tags["highway"] in self.settings_info["bikeFriendlyIfBikeLane"] and values[self.schema_info["field_name_bikelane"]] == 1:
                    values[self.schema_info["field_name_p_bicycle_mode"]] = 1

                #allow p_bike for certain tags and there is a bikelane and it is separate
                if tags["highway"] in self.settings_info["bikeFriendlyIfProtectedBikeLane"] and values[self.schema_info["field_name_separated_bike"]] == 1:
                    values[self.schema_info["field_name_p_bicycle_mode"]] = 1

                #allow walking if there are sidewalks
                if values[self.schema_info["field_name_sidewalk"]] == 1 or values[self.schema_info["field_name_separated_sidewalk"]] == 1:
                    values[self.schema_info["field_name_pedestrian_mode"]] = 1
                    values[self.schema_info["field_name_p_pedestrian_mode"]] = 1

                #if there isn't a bikelane and there are sidewalks allow bike, change the speed to pedestrian...
                if (values[self.schema_info["field_name_sidewalk"]] == 1 or values[self.schema_info["field_name_separated_sidewalk"]] == 1) and (values[self.schema_info["field_name_bikelane"]] == 0 and values[self.schema_info["field_name_separated_bike"]] == 0):
                    if values[self.schema_info["field_name_bicycle_mode"]] == 0:
                        values[self.schema_info["field_name_bicycle_mode"]] = 1
                        values[self.schema_info["field_name_speed_bicycle"]] = int(self.settings_info["default_bike_in_pedestrian"])
                    if values[self.schema_info["field_name_p_bicycle_mode"]] == 0:
                        values[self.schema_info["field_name_p_bicycle_mode"]] = 1
                        values[self.schema_info["field_name_speed_p_bike"]] = int(self.settings_info["default_bike_in_pedestrian"])

                #if foot == no, then no walking
                for sw in self.settings_info["setWalkToZeroIfNo"]:
                    if sw in tags:
                        if tags[sw] in ["no", "none"]:
                            values[self.schema_info["field_name_pedestrian_mode"]] = 0
                            values[self.schema_info["field_name_p_pedestrian_mode"]] = 0

                #TODO review this, might not be needed
                # This might be a problem as some footways (where it is ok to walk a bike) were tagged as bicycle:no
                # bicycleNo = 0
                # for sw in setBikeToZeroIfNo:
                #     if sw in tags:
                #         if tags[sw] in ["no", "none", "dismount"]:
                #             bicycleNo = 1
                #             if values["bikelane"] == 0 and values["separated_bike"] == 0:
                #                 if values["bike"] == 0:
                #                     values["bike"] = 1
                #                     values["speed_bike"] = default_bike_in_pedestrian
                #                 if values["p_bike"] == 0:
                #                     values["p_bike"] = 1
                #                     values["speed_p_bike"] = default_bike_in_pedestrian

                #if on a footway and bike isn't set allow slow bike...
                if tags['highway'] in self.settings_info["bikeOnFootway"]:
                    if values[self.schema_info["field_name_bicycle_mode"]] == 0:
                        values[self.schema_info["field_name_bicycle_mode"]] = 1
                        #if bicycleNo == 1:
                        values[self.schema_info["field_name_speed_bicycle"]] = int(self.settings_info["default_bike_in_pedestrian"])
                    if values[self.schema_info["field_name_p_bicycle_mode"]] == 0:
                        values[self.schema_info["field_name_p_bicycle_mode"]] = 1
                        #if bicycleNo == 1:
                        values[self.schema_info["field_name_speed_bicycle"]] = int(self.settings_info["default_bike_in_pedestrian"])

                #set preferred bike for steps
                if tags['highway'] in self.settings_info["bikeBarriers"]:
                    if values[self.schema_info["field_name_bicycle_mode"]] == 0:
                        values[self.schema_info["field_name_bicycle_mode"]] = 1
                        values[self.schema_info["field_name_speed_bicycle"]] = int(self.settings_info["default_bike_in_pedestrian"])


                    values[self.schema_info["field_name_p_bicycle_mode"]] = 0

                # clear out services etc.
                # Forbid automobile from the following types of facilities
                if tags["highway"] in self.settings_info["setRoadToZero"]:
                    values[self.schema_info["field_name_vehicle_mode"]] = 0
                    values[self.schema_info["field_name_truck_mode"]] = 0

                if tags["highway"] in self.settings_info["setTruckToZero"]:
                    values[self.schema_info["field_name_truck_mode"]] = 0

                if "hgv" in tags and tags["hgv"].lower() in self.settings_info.get("hgv_restrictions", []):
                    values[self.schema_info["field_name_truck_mode"]] = 0
                
                weight_tag = (
                    tags.get("maxweightrating:hgv_articulated") or 
                    tags.get("maxweightrating:hgv") or 
                    tags.get("maxweightrating") or
                    tags.get("maxweight:hgv_articulated") or 
                    tags.get("maxweight:hgv") or 
                    tags.get("maxweight")
                )
                if weight_tag:
                    weight_str = weight_tag.lower()
                    no_res = ["none", "unsigned", "no", "default", "signed:no", "unrestricted", "unknown"]
                    
                    if not any(marker in weight_str for marker in no_res):
                        is_restricted = True 
                        try:
                            # 1. Check for Pounds (lbs)
                            match_lbs = re.search(r"([0-9\.]+)\s*(lbs?|pounds?)", weight_str)
                            if match_lbs:
                                val_lbs = float(match_lbs.group(1))
                                if val_lbs >= 80000.0: # Standard 40-ton US Limit
                                    is_restricted = False
                            
                            # 2. Check for Tons (t) or Short Tons (st)
                            elif re.search(r"([0-9\.]+)\s*(t|tons?|st|short\s*tons?|metric\s*tons?)", weight_str):
                                match_tons = re.search(r"([0-9\.]+)", weight_str)
                                val_tons = float(match_tons.group(1))
                                if val_tons >= 40.0:
                                    is_restricted = False
                                    
                            # 3. OSM Default (Numeric only = Metric Tons)
                            elif re.match(r"^[0-9\.]+$", weight_str):
                                val_metric_tons = float(weight_str)
                                if val_metric_tons >= 36.3:
                                    is_restricted = False
                        except Exception: 
                            pass 
                            
                        if is_restricted:
                            values[self.schema_info["field_name_truck_mode"]] = 0
                
                if "maxheight" in tags:
                    height_str = tags["maxheight"].lower()
                    no_res = ["none", "unsigned", "no", "default", "signed:no", "unrestricted", "unknown"]
                    
                    if not any(marker in height_str for marker in no_res):
                        is_restricted = True 
                        try:
                            # Imperial check: 13.5 feet = 162 inches
                            match_imp = re.search(r"(\d+)\s*'\s*(?:(\d+)\s*\"?)?", height_str)
                            if match_imp:
                                feet = float(match_imp.group(1))
                                inches = float(match_imp.group(2)) if match_imp.group(2) else 0.0
                                total_inches = (feet * 12) + inches
                                if total_inches > 162.0:
                                    is_restricted = False
                            else:
                                # Metric check: 4.11 meters is approx 13.5 feet
                                match_met = re.search(r"([0-9\.]+)\s*(m|meters?|cm|centimeters?)?", height_str)
                                if match_met:
                                    val = float(match_met.group(1))
                                    meters = val / 100.0 if "cm" in (match_met.group(2) or "") else val
                                    if meters > 4.11:
                                        is_restricted = False
                        except Exception: pass
                        if is_restricted:
                            values[self.schema_info["field_name_truck_mode"]] = 0

                # --- PHYSICAL WIDTH CHECK ---
                if "maxwidth" in tags:
                    width_str = tags["maxwidth"].lower()
                    no_res = ["none", "unsigned", "no", "default", "signed:no", "unrestricted", "unknown"]
                    
                    if not any(marker in width_str for marker in no_res):
                        is_restricted = True
                        try:
                            # Imperial check for 8' 6" (102 inches)
                            match_imp = re.search(r"(\d+)\s*'\s*(?:(\d+)\s*\"?)?", width_str)
                            if match_imp:
                                feet = float(match_imp.group(1))
                                inches = float(match_imp.group(2)) if match_imp.group(2) else 0.0
                                total_inches = (feet * 12) + inches
                                if total_inches > 102.0:
                                    is_restricted = False
                            else:
                                # Metric check: 2.6 meters is the standard HGV threshold
                                match_met = re.search(r"([0-9\.]+)\s*(m|meters?|cm|centimeters?)?", width_str)
                                if match_met:
                                    val = float(match_met.group(1))
                                    meters = val / 100.0 if "cm" in (match_met.group(2) or "") else val
                                    if meters > 2.6:
                                        is_restricted = False
                        except Exception: pass
                        if is_restricted:
                            values[self.schema_info["field_name_truck_mode"]] = 0

                    for tag_k, tag_v in tags.items():
                        kl, vl = tag_k.lower(), tag_v.lower()
                        if "hgv" in kl and "conditional" in kl and "permit" in vl:
                            values[self.schema_info["field_name_truck_mode"]] = 0
                            break

                # Forbid bicycle and pedestrian from the following types of facilities
                if tags["highway"] in self.settings_info["setNonAutoToZeroHighway"]:
                    values[self.schema_info["field_name_pedestrian_mode"]] = 0
                    values[self.schema_info["field_name_p_pedestrian_mode"]] = 0
                    values[self.schema_info["field_name_bicycle_mode"]] = 0
                    values[self.schema_info["field_name_p_bicycle_mode"]] = 0

                if "motorway" in tags["highway"]:
                    values[self.schema_info["field_name_motorway"]] = 1
                else:
                    values[self.schema_info["field_name_motorway"]] = 0
                
                values[self.schema_info["field_name_reverse_bike_lane"]] = 0
                for f in self.settings_info["reverseBikeLaneYes"]:
                    if f in tags:
                        if tags[f] not in ['no', 'none']:
                            if values[self.schema_info["field_name_bicycle_mode"]] == 1 or values[self.schema_info["field_name_p_bicycle_mode"]] == 1:
                                values[self.schema_info["field_name_reverse_bike_lane"]] = 1
                for f in self.settings_info["reverseBikeLaneNo"]:
                    if f in tags:
                        if tags[f] in ['no', 'none', '-1']:
                            if values[self.schema_info["field_name_bicycle_mode"]] == 1 or values[self.schema_info["field_name_p_bicycle_mode"]] == 1:
                                values[self.schema_info["field_name_reverse_bike_lane"]] = 1

                values[self.schema_info["field_name_reverse_ped_allowed"]] = 0
                if values[self.schema_info["field_name_oneway"]] == "yes":
                    if values[self.schema_info["field_name_pedestrian_mode"]] == 1 or values[self.schema_info["field_name_p_pedestrian_mode"]] == 1:
                        values[self.schema_info["field_name_reverse_ped_allowed"]] = 1

                polylines = []
                start_node = None
                arr = []
                node_values = values
                not_zero = False
                #if not passable, do not include.
                mode_keys = [self.schema_info["field_name_vehicle_mode"],
                             self.schema_info["field_name_truck_mode"],
                             self.schema_info["field_name_pedestrian_mode"],
                             self.schema_info["field_name_bicycle_mode"],
                             self.schema_info["field_name_p_pedestrian_mode"],
                             self.schema_info["field_name_p_bicycle_mode"]
                             ]
                not_zero = any([values[x] for x in mode_keys])

                values[self.schema_info["field_name_prenetwork"]] = 1
                values[self.schema_info["field_name_postnetwork"]] = 1
                #if at least one mode value is 1 (allowed) on way, then render way and pull out its nodes as network nodes
                if not_zero is True:
                    for i, n in enumerate(v["nodes"]): #each way has several nodes
                        if n in nodes:
                            ll = nodes[n]
                            pnt_g = arcpy.PointGeometry(arcpy.Point(ll[1], ll[0]), helper_functions.get_wgs84_sr())
                            pnt_node = pnt_g.projectAs(self.utmsr)
                            pnt = arcpy.Point(ll[1], ll[0]) #create the point shape for the node
                            #TODO Too repetitive. Need to clean this up. Better node tracking?
                            if i == 0: #this is the first node
                                arr.append(pnt) #append the point to construct the line
                                nodes_to_insert[n]["SHAPE@"] = pnt_node
                                nodes_to_insert[n][self.schema_info["field_name_count"]] = node_count[n]
                                nodes_to_insert[n][self.schema_info["field_name_node_id"]] = n
                                nodes_to_insert[n][self.schema_info["field_name_link_origid"]] += values[self.schema_info["field_name_way_id"]] + "|"
                                nodes_to_insert[n][self.schema_info["field_name_highway"]] += values[self.schema_info["field_name_highway"]] + "|"
                                for x in mode_keys:
                                    nodes_to_insert[n][x] += values[x]
                                #not_zero = any([values[x] for x in ["road", "walk", "bike", "p_bike", "p_walk"]])
                                 #added to the node feature class later
                                start_node = n
                            elif i == len(v["nodes"])-1: #this is the last node
                                arr.append(pnt)
                                poly = arcpy.Polyline(arcpy.Array(arr), helper_functions.get_wgs84_sr())
                                polylines.append([poly, start_node, n])
                                nodes_to_insert[n]["SHAPE@"] = pnt_node
                                nodes_to_insert[n][self.schema_info["field_name_count"]] = node_count[n]
                                nodes_to_insert[n][self.schema_info["field_name_node_id"]] = n
                                nodes_to_insert[n][self.schema_info["field_name_link_origid"]] += values[self.schema_info["field_name_way_id"]] + "|"
                                nodes_to_insert[n][self.schema_info["field_name_highway"]] += values[self.schema_info["field_name_highway"]] + "|"
                                for x in mode_keys:
                                    nodes_to_insert[n][x] += values[x]
                            elif node_count[n] > 1: #if a node has more than one way associated with it, then split the line here
                                arr.append(pnt)
                                poly = arcpy.Polyline(arcpy.Array(arr), helper_functions.get_wgs84_sr())
                                polylines.append([poly, start_node, n])
                                arr = [] #reset the array
                                arr.append(pnt)
                                nodes_to_insert[n]["SHAPE@"] = pnt_node
                                nodes_to_insert[n][self.schema_info["field_name_count"]] = node_count[n]
                                nodes_to_insert[n][self.schema_info["field_name_node_id"]] = n
                                nodes_to_insert[n][self.schema_info["field_name_link_origid"]] += values[self.schema_info["field_name_way_id"]] + "|"
                                nodes_to_insert[n][self.schema_info["field_name_highway"]] += values[self.schema_info["field_name_highway"]] + "|"
                                for x in mode_keys:
                                    nodes_to_insert[n][x] += values[x]
                                start_node = n
                            else:
                                arr.append(pnt)
                        #else:
                            #values["missing_nodes"] = 1
                    #insert the lines into the feature class
                    for p, sn, en in polylines:
                    
                        #print(p.pointCount)
                        values[self.schema_info["field_name_length_meters"]] = p.getLength('geodesic', 'meters') #calculate the link length in meters
                        if values[self.schema_info["field_name_length_meters"]] > 0.0000000000001:
                            for m in self.schema_info["field_mode_prefix"]:
                                if values[f"speed_{m}"] > 0:
                                    values[f"fft_{m}"] = (3600 * values[self.schema_info["field_name_length_meters"]]) / (1609.344 * values[f"speed_{m}"]) #length = meters, maxspeed = mph
                                else:
                                    values[f"fft_{m}"] = None
                            values["SHAPE@"] = p.projectAs(self.utmsr)
                            values[self.schema_info["field_name_from_id"]] = sn
                            values[self.schema_info["field_name_to_id"]] = en
                            inputRow = [values[f] for f in ways_fields]
                            ic.insertRow(inputRow)
                            values["SHAPE@"] = None

        arcpy.ResetProgressor()
        
        #NOTE maybe collapse the duplicate nodes here
        self.messages.send_message("Inserting nodes.")
        arcpy.SetProgressor("step", "Inserting points into osm_junctions...",
            0, len(nodes_to_insert.keys()), 1)
        with arcpy.da.InsertCursor(str(self.fc_nodes), nodes_fields) as ic:
            for _, values in nodes_to_insert.items():
                arcpy.SetProgressorPosition()
                if values["SHAPE@"] is not None:
                    if "motorway" in values[self.schema_info["field_name_highway"]]:
                        values[self.schema_info["field_name_motorway"]] = 1
                    else:
                        values[self.schema_info["field_name_motorway"]] = 0
                    ic.insertRow([values[f] for f in nodes_fields])
        existing_fields = arcpy.ListFields(str(self.fc_nodes))
        for f in existing_fields:
            if f.name not in nodes_fields and not f.required:
                arcpy.DeleteField_management(str(self.fc_nodes), f.name)

    def build_fc(self):
        """
            Creates the feature classes for osm_ways and osm_junctions inside the project geodatabase.
            Args:
                None
            Returns:
                Files written to the project folder.
        """     
        
        self.ways_fields_to_add = self.schema_info["project_ways_fc"] + self.schema_info["project_ways_nodes_fc"] + self.schema_info["prepost_fields"]
        self.nodes_fields_to_add = self.schema_info["project_nodes_fc"] + self.schema_info["project_ways_nodes_fc"]

        self.fc_ways = helper_functions.drop_add_featureclass(Path(self.project_fgdb), self.schema_info["fc_name_project_ways"], "POLYLINE", self.utmsr,"32_BIT") #oid must be 32 bit to be compatible with Network Analyst
        self.fc_nodes = helper_functions.drop_add_featureclass(Path(self.project_fgdb), self.schema_info["fc_name_project_nodes"], "POINT", self.utmsr,"32_BIT")

        for f in self.ways_fields_to_add:
            f["featureClass"] = self.fc_ways
            helper_functions.drop_add_field(**f)

        for f in self.nodes_fields_to_add:
            f["featureClass"] = self.fc_nodes
            helper_functions.drop_add_field(**f)

        self.set_metadata_attribution(self.fc_ways, "Network Lines", "Network, Segments", "Network lines generated from OpenStreetMap ways with highway tags.", "Network lines generated from OpenStreetMap ways with highway tags.")
        self.set_metadata_attribution(self.fc_nodes, "Network Junctions", "Network, Junctions", "Network junctions generated from OpenStreetMap ways with highway tags.", "Network junctions generated from OpenStreetMap ways with highway tags.")

class process_OSM_pois(processor):
    def __init__(self, projectFolder:Path, osmFile:Path, projFGDB:Path, messages:custMessenger=None):
        """
            OSM pois processor inherits from processor class. Run separate_osm_data() first then build_data()
            Args:
                projectFolder (Path): folder where the project data is written.
                osmFile (Path): OSM XML file to process.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                process_OSM_ways object
        """
        super().__init__(projectFolder, projFGDB, messages)
        self.osm_file = osmFile
        self.fields_to_add = None
        self.fc_pois = None
        self.pois_data = None
        self.ways_tracking = None
        self.nodes_tracking = None
        self.pcm = POICategoryManager(projectFolder, projFGDB)

    def separate_osm_data(self):
        """
            Parses the input OSM XML file and extracts Points-of-Interest node data, associating nodes with any ways and relations that reference them. Writes a pickled dictionary containing OSM node-POI nodes key-value pairs. This output informs the build_data method.
            Args:
                None
            Returns:
                Files written to the project folder (as {project_name}_pois.data).
        """
        out_file_root = self.project_folder.name.replace("_project","")
        #store information about the nodes
        self.nodes_tracking = {}
        #store information from the ways
        self.ways_tracking = {}


        #start the progressor to see in the arcypy

        arcpy.SetProgressor("step", "Processing nodes...",
            0, 100, 1)
        tracking_progress = 1
        arcpy.AddMessage("Finding nodes")
        #iterparse efficiently iterates over the xml file without loading it entirely in memory
        for ev, n in ET.iterparse(str(self.osm_file), events=('end',), tag="node"):
            if n.attrib["id"] not in self.nodes_tracking:
                tags = n.findall('tag')
                #add the node by id, add the tag information and coords
                self.nodes_tracking[n.attrib["id"]] = {"tags":{x.attrib["k"]: x.attrib["v"] for x in tags},
                                                   "way_id":[],
                                                   "coords":(float(n.attrib["lat"]),float(n.attrib["lon"]))}
                
                del tags #clear to remove from memory
            n.clear() #clear to remove from memory
            if ev == 'end':
                n.clear()
            #increase progressor step
            tracking_progress += 1
            if tracking_progress == 100:
                tracking_progress = 1
        
        #reset progressor for next iteration
        arcpy.SetProgressor("step", "Processing ways...",
            0, 100, 1)
        tracking_progress = 1
        arcpy.AddMessage("Finding ways")
        #iterate to find the ways and track their nodes and tags
        for ev, w in ET.iterparse(str(self.osm_file), events=('end',), tag="way"):
            way_id = w.attrib["id"]
            nds = w.findall('nd')
            self.ways_tracking[way_id] = {"nodes":[], "tags":{}}
            way_tags = w.findall('tag')

            for x in nds:
                nd_id = x.attrib["ref"]
                self.ways_tracking[way_id]["nodes"].append(nd_id)
                if nd_id in self.nodes_tracking:
                    self.nodes_tracking[nd_id]["way_id"].append(way_id)  #track the nodes with no way ids
                #get all the tags for the ways
                for t in way_tags:
                    self.ways_tracking[way_id]["tags"][t.attrib["k"]] = t.attrib["v"]

            del nds
            del way_tags

            if ev == 'end':
                w.clear()

            tracking_progress += 1
            if tracking_progress == 100:
                tracking_progress = 1
        arcpy.ResetProgressor()
        arcpy.SetProgressor("step", "Processing relation...",
            0, 100, 1)
        tracking_progress = 1


        arcpy.AddMessage("Finding relations")
        for ev, w in ET.iterparse(str(self.osm_file), events=('end',), tag="relation"):
            
            membs = w.findall('member')
            tags = w.findall('tag')
            #find the members of the relation, look for ways, and assign the tags from the relation to the way
            for x in membs:
                if x.attrib["type"] == "way":
                    way_id = x.attrib["ref"]
                    if way_id in self.ways_tracking:
                            for t in tags:
                                if t.attrib["k"] not in self.ways_tracking[way_id]["tags"]:
                                    self.ways_tracking[way_id]["tags"][t.attrib["k"]] = t.attrib["v"]
            del membs
            del tags

            if ev == 'end':
                w.clear()

            tracking_progress += 1
            if tracking_progress == 100:
                tracking_progress = 1

        self.pois_data = []
        for k, v in self.ways_tracking.items():
            for nd in v["nodes"]:
                if nd in self.nodes_tracking:
                    coords = self.nodes_tracking[nd]["coords"]
                    self.pois_data.append({"way_id":k, "node_id":nd, "coords":coords, "tags":v["tags"]})
        for k, v in self.nodes_tracking.items():
            if len(v["way_id"]) == 0 and len(v["tags"].keys())>0:
                self.pois_data.append({"way_id":None, "node_id":k, "coords":v["coords"], "tags":v["tags"]})

        arcpy.AddMessage("Saving to data file.")
        with open(self.project_folder / f"{out_file_root}_pois.data", 'wb') as outf:
            pickle.dump(self.pois_data, outf, protocol=4)
        with open(self.project_folder / f"{out_file_root}_pois_nodes.data", 'wb') as outf:
            pickle.dump(self.nodes_tracking, outf, protocol=4)

    def build_data(self):
        """
            Build and insert Points of Interest (POI) features into the project geodatabase. Reads preprocessed POI from disk, classifies each POI into configured categories based on OSM tags, constructs point geometries in the project coordinate system, and inserts one or more feature rows per POI into the POI feature class.
            Args:
                None
            Returns:
                None
        """    
        out_file_root = self.project_folder.name.replace("_project","")
        if self.pois_data is None:
            with open(self.project_folder / f"{out_file_root}_pois.data", 'rb') as infile:
                self.pois_data = pickle.load(infile)
        if self.nodes_tracking is None:
            with open(self.project_folder / f"{out_file_root}_pois_nodes.data", 'rb') as infile:
                self.nodes_tracking = self.pois_data = pickle.load(infile)

        self.build_fc()
        
        categories_to_fields = self.pcm.get_category_fields()
        binary_fields = [v for v in categories_to_fields.values()]
        fields = ["SHAPE@"] + [v["field_name"] for v in self.fields_to_add] + binary_fields

        arcpy.ResetProgressor()
        arcpy.SetProgressor("step", "Inserting POI into feature class...",
            0, len(self.pois_data), 1)
            
        with arcpy.da.InsertCursor(str(self.fc_pois), fields) as ic:
            for _v in self.pois_data:
                add_node = True
                tags = _v["tags"]
                arcpy.SetProgressorPosition()
                #TODO: move this to schema?
                #Defines the tags to exclude

                
                values = {f:None for f in fields}


                #add the node id
                values[self.schema_info["field_name_poi_original"]] = _v["node_id"] 
                values[self.schema_info["field_name_poi_wayid"]] = _v["way_id"]


                #handle the tags by pipe delimited
                values[self.schema_info["field_name_alltags"]] = "|".join(f"{k}:{v}" for k,v in tags.items())



                #length cutoff for ways with a lot of tags
                if len(values[self.schema_info["field_name_alltags"]]) >799:
                    values[self.schema_info["field_name_alltags"]] = values[self.schema_info["field_name_alltags"]][:790]

                matched_categories, matched_classes = self.pcm.classify(tags)
                #project the coordinates into the project utm
                pnt = arcpy.PointGeometry(arcpy.Point(_v["coords"][1], _v["coords"][0]), helper_functions.get_wgs84_sr()).projectAs(self.utmsr)
                values["SHAPE@"] = pnt
                #string version of the matched categories
                values[self.schema_info["field_name_poi_fclass"]] = '|'.join(sorted(matched_classes)) if matched_classes else None
                
                #create the binary flags for the values
                
                for cat, field_name in categories_to_fields.items():
                    values[field_name] = 1 if cat in matched_categories else 0
                
                   
                #dont bother inserting if there were no category matches
                if all(values[field] == 0 or values [field] is None for field in binary_fields):
                    continue    
                
                values[self.schema_info["field_name_poi_finalid"]] = None
                if _v["way_id"] is None:
                    values[self.schema_info["field_name_poi_finalid"]] = f"POINT_{values[self.schema_info['field_name_poi_original']]}"
                    ic.insertRow([values[f] for f in fields])
                else:
                    values[self.schema_info["field_name_poi_finalid"]] = _v["way_id"]
                    ic.insertRow([values[f] for f in fields])


        arcpy.ResetProgressor()

    def build_fc(self):
        """
            Creates/builds the schema of the Points of Interest (POI) feature class. Reads POI categories from settings, constructs the POI feature class in the project file geodatabase, and adds both the base attribute fields and binary category indicator fields. It also sets metadata attribution on the created feature class. Called within the build_data method before inserting individual points.
            Args:
                None
            Returns:
                None
        """


        self.fields_to_add = self.schema_info["pois_fields"]

        self.fc_pois = helper_functions.drop_add_featureclass(Path(self.project_fgdb), self.schema_info["fc_name_project_pois_nodes"], "POINT", self.utmsr,"32_BIT") #oid must be 32 bit to be compatible with Network Analyst

        #Add base fields to the feature class
        for f in self.fields_to_add:
            f["featureClass"] = self.fc_pois
            helper_functions.drop_add_field(**f)


        self.pcm.add_categories_as_fields(self.fc_pois)

        self.set_metadata_attribution(self.fc_pois, "POI Data", "POI, nodes", "POI generated from OpenStreetMap nodes and ways using tags.", "POI generated from OpenStreetMap nodes and ways using tags.")


class process_OSM_water(processor):
    def __init__(self, projectFolder:Path, osmFile:Path, projFGDB:Path, envelope:arcpy.Polygon, messages:custMessenger=None):
        """
            OSM pois processor inherits from processor class. Run separate_osm_data() first then build_data()
            Args:
                projectFolder (Path): folder where the project data is written.
                osmFile (Path): OSM XML file to process.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                process_OSM_ways object
        """
        super().__init__(projectFolder, projFGDB, messages)
        self.osm_file = osmFile
        self.fields_to_add = None
        self.fc_water = None
        self.envelope = envelope
    
    def separate_osm_data(self):
        # Parses the OSM XML file in three passes using xml.etree.ElementTree.iterparse:
            # First pass: read all elements and store node coordinates in nodes dict keyed by node id: nodes[id] = (lon, lat).
            # Second pass: read all elements and store ordered node references for each way in ways dict: ways[way_id] = [node_ref, ...].
            # Third pass: read all elements, collecting member way ids for members with role="outer" into relations dict: relations[relation_id] = [way_id, ...].
            # Each parsed element is cleared to reduce memory usage.
        # Orders ways for each relation to form a continuous outer ring:
            # For each relation with outer way ids, start from the first way and attempt to chain remaining ways so the last node of the current way matches the first node of the next way.
            # If a next way’s last node matches the current last node, the code reverses that way’s node list to align orientation and continues.
            # If a continuous chain cannot be formed, it prints a warning and stops chaining for that relation.
            # Builds ordered_relations: relation_id -> ordered list of way ids.
        # Inserts polygons into the feature class:
            # Opens an arcpy.da.InsertCursor on the water feature class with fields ["SHAPE@", water id field].
            # For each ordered relation:
                # Concatenates the node coordinates for all ordered ways into a single list of arcpy.Point objects, creates an arcpy.Polygon (SpatialReference 4326), and inserts it with the relation id.
                # Tracks way ids used (check_ways).
            # For standalone ways not part of processed relations:
                # Converts each way’s node list into an arcpy.Polygon and inserts it with the way id.
            # Finally, projects the inserted feature class to a UTM feature class in the project geodatabase via arcpy.Project_management.
        out_file_root = self.project_folder.name.replace("_project","")
        self.build_fc()
        relations = {}
        ways = {}
        nodes = {}
        for ev, n in ET.iterparse(str(self.osm_file), events=('end',), tag="node"):
            if n.attrib["id"] not in nodes:
                nodes[n.attrib["id"]] = (float(n.attrib["lon"]), float(n.attrib["lat"]))
            n.clear()
            if ev == 'end':
                n.clear()

        for ev, w in ET.iterparse(str(self.osm_file), events=('end',), tag="way"):
            nds = w.findall('nd')
            ways[w.attrib["id"]] = [x.attrib["ref"] for x in nds]
            w.clear()
        check_ways = []
        for ev, w in ET.iterparse(str(self.osm_file), events=('end',), tag="relation"):
            nds = w.findall('member')
            relations[w.attrib["id"]] = []
            for m in nds:
                if m.attrib["type"] == "way":
                    if m.attrib["role"] == "outer":
                        relations[w.attrib["id"]].append(m.attrib["ref"])
            w.clear()

        ordered_relations = {}
        for k,v in relations.items():
            ordered_ways = []
            ordered_relations[k] = []
            if len(v) > 0:
                current_way_id = v[0]
                ordered_ways.append(current_way_id)
                remaining_ways = set(v) - {current_way_id}
                previousLen = len(remaining_ways)
                while remaining_ways:
                    
                    found_next = False
                    current_way_nodes = ways[current_way_id]
                    last_node_of_current = current_way_nodes[-1]

                    if last_node_of_current == current_way_nodes[0]:
                        current_way_id = list(remaining_ways)[0]
                        if current_way_id not in ordered_ways:
                            ordered_ways.append(current_way_id)
                        remaining_ways.remove(current_way_id)
                        found_next = True
                    else:
                        for next_way_id in list(remaining_ways): # Iterate over a copy
                            next_way_node_list = ways[next_way_id]
                            
                            if next_way_node_list[0] == last_node_of_current:
                                ordered_ways.append(next_way_id)
                                current_way_id = next_way_id
                                remaining_ways.remove(next_way_id)
                                found_next = True
                                break
                            elif next_way_node_list[-1] == last_node_of_current: # Handle reversed ways
                                ordered_ways.append(next_way_id)
                                ways[next_way_id].reverse() # Reverse nodes for consistency
                                current_way_id = next_way_id
                                remaining_ways.remove(next_way_id)
                                found_next = True
                                break
                            else:
                                lon1, lat1 = nodes[last_node_of_current]
                                next_way_node_list = ways[next_way_id]
                                lon2, lat2 = nodes[next_way_node_list[0]]

                                geodesic = helper_functions.geodesic(lat1, lon1, lat2, lon2)
                                closest_geodesic = .0000001
                                candidateWay = None
                                reverses = None
                                if geodesic < closest_geodesic:
                                    closest_geodesic = geodesic
                                    candidateWay = next_way_id
                                    reverses = False
                                lon2, lat2 = nodes[next_way_node_list[-1]]
                                geodesic = helper_functions.geodesic(lat1, lon1, lat2, lon2)
                                if geodesic < closest_geodesic:
                                    closest_geodesic = geodesic
                                    candidateWay = next_way_id
                                    reverses = True
                                if candidateWay is not None:
                                    ordered_ways.append(candidateWay)
                                    if reverses is True:
                                        ways[candidateWay].reverse()
                                    current_way_id = candidateWay
                                    remaining_ways.remove(candidateWay)
                                    found_next = True
                                    break
                    if found_next is False:
                        #self.messages.send_message(f"{k} breaking {current_way_id} {remaining_ways} {ordered_ways}", custTypes.INFORMATION)
                        ordered_relations[k].append(ordered_ways)
                        try:
                            remaining_ways.remove(current_way_id)
                        except:
                            pass
                        if len(remaining_ways) == 1:
                            ordered_relations[k].append([remaining_ways.pop()])
                        elif len(remaining_ways) > 1:
                            current_way_id = remaining_ways.pop()
                            ordered_ways = []

                        #break
                        # if not found_next:
                        #     lon1, lat1 = nodes[last_node_of_current]
                        #     closest_geodesic = .0000001
                        #     candidateWay = None
                        #     reverses = None
                        #     for next_way_id in list(remaining_ways):
                        #         next_way_node_list = ways[next_way_id]
                        #         lon2, lat2 = nodes[next_way_node_list[0]]
                        #         geodesic = helper_functions.geodesic(lat1, lon1, lat2, lon2)
                        #         if geodesic < closest_geodesic:
                        #             closest_geodesic = geodesic
                        #             candidateWay = next_way_id
                        #             reverses = False
                        #         lon2, lat2 = nodes[next_way_node_list[-1]]
                        #         geodesic = helper_functions.geodesic(lat1, lon1, lat2, lon2)
                        #         if geodesic < closest_geodesic:
                        #             closest_geodesic = geodesic
                        #             candidateWay = next_way_id
                        #             reverses = True

                        #     if candidateWay is not None:
                        #         ordered_ways.append(candidateWay)
                        #         if reverses is True:
                        #             ways[candidateWay].reverse()
                        #         current_way_id = candidateWay
                        #         remaining_ways.remove(candidateWay)
                        #         self.messages.send_message(f"Used Distance on {k}, {remaining_ways}", custTypes.WARNING)
                        #     else:
                        #         pass#self.messages.send_message(f"Warning: Could not find a continuous chain for relation {k}, {remaining_ways}", custTypes.WARNING)
                            
                ordered_relations[k].append(ordered_ways)

        with arcpy.da.InsertCursor(str(self.fc_water), ["SHAPE@", self.schema_info["field_name_water_id"]]) as ic:
            check_ways = []
            for k,polygons in ordered_relations.items():
                if len(v) > 0:
                    
                    for v in polygons:
                        combo = []
                        for wid in v:
                            combo += [arcpy.Point(*nodes[coord]) for coord in ways[wid]]
                            check_ways.append(wid)
                        #self.messages.send_message(self.signed_area(combo), custTypes.INFORMATION)
                        #area = self.signed_area(combo)
                        #if area > 0:
                        #    combo.reverse()
                        #    if combo[0] != combo[-1]:
                        #        combo.append(combo[0])
                        #combo = self.remove_consecutive_duplicates(combo)
                        outer_polygon = arcpy.Polygon(arcpy.Array(combo), arcpy.SpatialReference(4326))
                        ic.insertRow([outer_polygon, k])
                    
            for k,v in ways.items():
                if k not in check_ways:
                    arr = arcpy.Array([arcpy.Point(*nodes[x]) for x in v])
                    poly = arcpy.Polygon(arr, arcpy.SpatialReference(4326))
                    ic.insertRow([poly, k])

        proj_water = arcpy.management.Project(str(self.fc_water), str(self.project_fgdb / f"{self.schema_info['fc_name_water_utm']}"), self.utmsr).getOutput(0)
        self.set_metadata_attribution(proj_water, "Water Data", "Water, Polygons", "Water ways generated from OpenStreetMap ways using tags.", "Water ways generated from OpenStreetMap ways using tags.")

        if arcpy.Exists("memory//dissolve_water"):
            arcpy.Delete_management("memory//dissolve_water")
        arcpy.AddMessage("Dissolving water features")
        water_dissolve = arcpy.PairwiseDissolve_analysis(proj_water, "memory/dissolve_water").getOutput(0)
        water_shapes = [row[0] for row in arcpy.da.SearchCursor(water_dissolve, ["SHAPE@"])]

        arcpy.SetProgressor("step", "Creating inverse feature layer...",
            0, len(water_shapes), 1)

        envelope_utm = self.envelope.projectAs(self.utmsr)

        for row in water_shapes:
            if row is not None:
                envelope_utm = envelope_utm.difference(row)
                arcpy.SetProgressorPosition()
        arcpy.ResetProgressor()
        with arcpy.da.InsertCursor(str(self.land_area), ["SHAPE@"]) as ic:
            ic.insertRow([envelope_utm])

        if arcpy.Exists(str(self.fc_water)):
            arcpy.Delete_management(str(self.fc_water))

    def build_fc(self):
        self.fields_to_add = [
            {"featureClass":None,"field_name":self.schema_info["field_name_water_id"],"field_type":"TEXT", "field_length":100, "add_index":True}
            ]

        self.fc_water = helper_functions.drop_add_featureclass(Path(self.project_fgdb), "water_features", "POLYGON", arcpy.SpatialReference(4326),"32_BIT")
        self.land_area = helper_functions.drop_add_featureclass(Path(self.project_fgdb), self.schema_info["land_area"], "POLYGON", self.utmsr,"32_BIT")
        for f in self.fields_to_add:
            f["featureClass"] = self.fc_water
            helper_functions.drop_add_field(**f)
		
        self.set_metadata_attribution(self.fc_water, "Water Data", "Water, Polygons", "Water ways generated from OpenStreetMap ways using tags.", "Water ways generated from OpenStreetMap ways using tags.")