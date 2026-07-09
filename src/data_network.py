import arcpy
import json
import math
import multiprocessing as mp
import numpy as np
import numpy.typing as npt
import os
import pandas as pd
import pickle
import seaborn as sns
import time
import uuid
import yaml

from collections import Counter
from datetime import datetime
from operator import itemgetter
from pathlib import Path
from typing import Literal, List, Any

from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import shortest_path

from static_tools import helper_functions
from static_tools import random_id
from managers import settingsManager

class network_class(object):
    """
        Class representing a modal network
            Contains methods to construct a network graph in scipy and 
            calculate shortest paths on the network graph.

        Parameters:
            mode (str): mode to build the network for.
            networkID (str): ID for the network.
            linksFC (Path): path to the OSM links feature class.

        Side Effects:
            - Builds network graph.
            - Calculates distance matrix for the mode.

        Notes:
            - No notes!
    """    
    _TYPES_LENGTH = Literal['length', 'fft']

    def __init__(self, mode:str, networkID:str, linksFC:Path) -> None:
        """
            Initialize class representing a modal network
            Args:
                mode (str): mode to build the network for.
                networkID (str): ID for the network.
                linksFC (Path): path to the OSM links feature class.
            Returns:
                None
        """
        self.mode = mode
        self.uid = networkID
        self.linksFC = linksFC # feature class with the links for the network
        self.links = None
        self.node_id_to_index = None
        self.index_to_node_id = None
        self.G = None
        self.file_path = Path(__file__).parents[0]
        self.schema_info = None
        self.load_schema()
        self.weight_fields = [self.schema_info["field_name_length_meters"]] # add length field to the weight fields
        self.set_fft() # set the fft field based on the mode

    def load_schema(self) -> None:
        """
            Loads the settings schema file, stores as schema_info variable
            Args:
                None
            Returns:
                None
        """
        with open(self.file_path / 'schema.yaml', 'r') as f:
            self.schema_info = yaml.load(f, Loader=yaml.Loader)

    def set_fft(self) -> None:
        """
            Sets the fft field based on the mode
            Args:
                None
            Returns:
                None
        """
        if self.mode == self.schema_info["field_name_vehicle_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_vehicle"])
        elif self.mode == self.schema_info["field_name_truck_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_truck"])
        elif self.mode == self.schema_info["field_name_pedestrian_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_ped"])
        elif self.mode == self.schema_info["field_name_bicycle_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_bike"])
        elif self.mode == self.schema_info["field_name_p_bicycle_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_p_bike"])
        elif self.mode == self.schema_info["field_name_p_pedestrian_mode"]:
            self.weight_fields.append(self.schema_info["field_name_fft_ped"])        
    
    def build_network(self, prenetwork:bool=True, edge_weight:str="fft") -> None:
        """
            Builds the network, stores as G variable
            Args:
                prenetwork(bool): prenetwork or postnetwork indicator
                edge_weight(str): attribute to use for calculating shortest paths, should be "fft" or "length"
            Returns:
                None
        """
        start_time = time.time()
        # get the links from the feature class based on the mode and prenetwork/postnetwork
        self.links, self.node_id_to_index, self.index_to_node_id = self.get_links(prenetwork, edge_weight)
        end_time = time.time()
        elapsed_time = end_time - start_time
        arcpy.AddMessage(f"{elapsed_time} seconds to get the links")
        start_time = time.time()
        # use coo_matrix method to build sparse matrix representation of network
        self.G = coo_matrix((self.links[2], (self.links[0], self.links[1])), shape=(len(self.node_id_to_index.keys()), len(self.node_id_to_index.keys())))
        end_time = time.time()
        elapsed_time = end_time - start_time
        arcpy.AddMessage(f"{elapsed_time} seconds to build the digraph")
    
    def get_links(self, prenetwork:bool, edge_weight:str="fft") -> list:
        """
            Gets the links from the feature class based on mode and pre/post
            Args:
                prenetwork(bool): prenetwork or postnetwork indicator
                edge_weight(str): attribute to use for calculating shortest paths, should be "fft" or "length"
            Returns:
                List of network link data. First return argument is sparse matrix notation of edge weights by from and to nodes.
                Second return argument is node mapping. Third return argument is reverse node mapping.
        """
        if prenetwork is True:
            wc = f"{self.mode} = 1 and {self.schema_info['field_name_prenetwork']} = 1"
        elif prenetwork is False:
            wc = f"{self.mode} = 1 and {self.schema_info['field_name_postnetwork']} = 1"
        data_l = []
        col_l = []
        row_l = []
        nodes = {}
        index_nodes = {}
        node_index = 0
        weight_index = 1
        if edge_weight == "length":
            weight_index = 0
        edge_dict = {}
        with arcpy.da.SearchCursor(str(self.linksFC), [self.schema_info["field_name_from_id"], self.schema_info["field_name_to_id"], self.schema_info["field_name_oneway"], self.weight_fields[weight_index]], where_clause = wc) as sc:
            for row in sc:
                fromID = None
                toID = None
                if row[0] not in nodes:
                    # record a new node ID
                    nodes[row[0]] = node_index
                    fromID = node_index
                    node_index +=1
                else:
                    fromID = nodes[row[0]]
                if row[1] not in nodes:
                    # record a new node ID
                    nodes[row[1]] = node_index
                    toID = node_index
                    node_index +=1
                else:
                    toID = nodes[row[1]]
                if fromID is not None and toID is not None:
                    w = row[3]
                    if (fromID, toID) not in edge_dict or w < edge_dict[(fromID, toID)]:
                        edge_dict[(fromID, toID)] = w

                        if row[2] != 'yes':
                            if (toID, fromID)not in edge_dict or w < edge_dict[(toID, fromID)]:
                                edge_dict[(toID, fromID)] = w
        for (u, v), w in edge_dict.items():
            row_l.append(u)
            col_l.append(v)
            data_l.append(w)
        # create reverse node mapping
        index_nodes = {v:k for k,v in nodes.items()}
        return [np.array(row_l), np.array(col_l), np.array(data_l)], nodes, index_nodes

    def find_distances(self, node_ids:npt.ArrayLike, dest_ids:npt.ArrayLike) -> npt.NDArray[Any]:
        """
            Calculates network length from origin nodes to destination nodes
            Args:
                node_ids(array_like): NumPy array of origin network graph IDs
                dest_ids(array_like): NumPy array of destination network graph IDs
            Returns:
                Distance matrix subset to just node_ids origins and dest_ids destinations
        """
        return shortest_path(csgraph=self.G, directed=True, return_predecessors=False, indices=node_ids)[:, dest_ids]
    
    def distance_origins_to_destinations(self, node_origin_osm_ids:List[Any], node_destination_osm_ids:List[Any], filename:Path) -> None:
        """
            Calculates and saves shortest path distances to file
            Args:
                node_origin_osm_ids(List): list of OSM IDs for origins
                node_destination_osm_ids(List): list of OSM IDs for destinations
                filename(Path): filepath for saving distance matrix
            Returns:
                None
        """
        # create arrays of graph IDs for origins and destinations
        self.node_ids = [self.node_id_to_index[x] for x in node_origin_osm_ids if x in self.node_id_to_index]
        self.dest_ids = np.unique(np.array([self.node_id_to_index[x] for x in node_destination_osm_ids if x in self.node_id_to_index]))
        self.clean_dest_osm_ids = np.array([self.index_to_node_id[x] for x in self.dest_ids])
        nodesosm = [self.index_to_node_id[x] for x in self.node_ids]
        # calculate distances between subset of origins and destinations
        self.dm = self.find_distances(self.node_ids, self.dest_ids)
        arcpy.AddMessage(f"Saving distance matrix as feather pandas file type {filename}")
        df = pd.DataFrame(self.dm, columns=self.clean_dest_osm_ids, index=nodesosm)
        #df = df[self.clean_dest_osm_ids[~np.all(np.isinf(df[self.clean_dest_osm_ids].values), axis=0)]]
        df.reset_index().rename(columns={"index":"from"}).to_feather(filename)
        # clear up memory
        del df
        del self.dm

    def reconstruct_path(self, predecessors:npt.NDArray[Any], source:int, destination:int) -> List[Any]:
        """
            Reconstructs shortest path from predecessors array
            Args:
                predecessors(array_like): array of predecessor node IDs along shortest path
                source(int): graph ID for the origin ID
                destination(int): graph ID for the destination ID
            Returns:
                List of graph IDs in consecutive order from source to destination
        """
        path = []
        current_node = destination
        # construct path as list of graph IDs
        while current_node != source and current_node != -9999: # -9999 indicates no path
            path.insert(0, current_node) # insert at the beginning to build path in correct order
            current_node = int(predecessors[current_node])
        
        if current_node == source:
            # add source as first graph ID in path
            path.insert(0, source)
            return path
        else:
            return [] # No path found

    def find_path_between_origin_and_destination(self, origin_id:str, destination_id:str) -> List[Any]:
        """
            Calculates the shortest path between origin and destination
            Args:
                origin_id(str): origin node ID
                destination_id(str): destination node ID
            Returns:
                List of node IDs specifying the path between origin and destination nodes
        """
        # if the origin id is not in the node id to index dictionary, raise an exception
        if origin_id not in self.node_id_to_index:
            raise Exception("Origin Node ID not part of network.")
        # if the destination id is not in the node id to index dictionary, raise an exception
        if destination_id not in self.node_id_to_index:
            raise Exception("Destination Node ID not part of network.")
        origin_g_id = self.node_id_to_index[origin_id] # get the graph id for the origin id
        dest_g_id = self.node_id_to_index[destination_id] # get the graph id for the destination id
        # find the shortest path from the origin to all nodes
        dist, predecessors = shortest_path(csgraph=self.G, directed=True, return_predecessors=True, indices=origin_g_id)

        # reconstruct the path from the predecessors array
        path = self.reconstruct_path(predecessors, origin_g_id, dest_g_id)
        if len(path) == 0:
            return None
        else:
            return [self.index_to_node_id[x] for x in path] # return the path as a list of node ids


class network_manager(settingsManager):
    """
        Class to build a network
            Contains methods to build a network for different modes and 
            calculate free-flow travel time shortest paths.

        Parameters:
            projectFolder (Path): folder where the project data is written.
            projFGDB (Path): project file geodatabase where the processed OSM data is written.
            scenarioName (str): name of scenario

        Side Effects:
            - Builds network files.
            - Calculates distance matrices by mode and pre/post.

        Notes:
            - No notes!
    """
    _TYPES_MODES = Literal['vehicle', 'truck', 'bike', 'pedestrian', 'p_bike', 'p_pedestrian']
    MODE_VEHICLE = "vehicle"
    MODE_TRUCK = "truck"
    MODE_PEDESTRIAN = "pedestrian"
    MODE_BICYCLE = "bike"
    MODE_PREFERRED_BICYCLE = "p_bike"
    MODE_PREFERRED_PEDESTRIAN = "p_pedestrian"
    ALL_MODES = [
        MODE_VEHICLE,
        MODE_TRUCK,
        MODE_BICYCLE,
        MODE_PEDESTRIAN,
        MODE_PREFERRED_BICYCLE,
        MODE_PREFERRED_PEDESTRIAN]

    def __init__(self, projectFolder:Path, scenarioName:str) -> None:
        """
            Initialize class to build a network
            Args:
                projectFolder(Path): folder where the project data is written
                projFGDB(Path): project file geodatabase where the processed OSM data is written
                scenarioName(str): name of scenario
            Returns:
                None
        """

        super().__init__(projectFolder, scenario_name=scenarioName)

        
        self.scenario_folder = self.project_folder / self.scenario_name
        self.scenario_fgdb = self.scenario_folder / f"{self.scenario_name}.gdb"
        self.network_table = self.scenario_fgdb / self.schema_info["fc_network_table"]

        self.create_network_table()
        self.get_existing_networks()
        self.results = {}
        self.MODE_BICYCLE = self.schema_info["field_name_bicycle_mode"]
        self.MODE_VEHICLE = self.schema_info["field_name_vehicle_mode"]
        self.MODE_TRUCK = self.schema_info["field_name_truck_mode"]
        self.MODE_PEDESTRIAN = self.schema_info["field_name_pedestrian_mode"]
        self.MODE_PREFERRED_PEDESTRIAN = self.schema_info["field_name_p_pedestrian_mode"]
        self.MODE_PREFERRED_BICYCLE = self.schema_info["field_name_p_bicycle_mode"]


    def create_network_table(self) -> None:
        """
            Creates the network table if does not exist and add required fields
            Args:
                None
            Returns:
                None
        """
        if arcpy.Exists(str(self.network_table)) is False:
            # if there is no network table, create it
            # create fields for network ID, mode, prepost label, and filename
            self.network_table = arcpy.CreateTable_management(str(self.scenario_fgdb), self.schema_info["fc_network_table"]).getOutput(0)
            for f in self.schema_info["network_table_fields"]:
                f["featureClass"] = self.network_table
                helper_functions.drop_add_field(**f)

    def get_existing_networks(self) -> None:
        """
            Gets list of existing network IDs and modes, stores as network_ids and mode_id variables, respectively
            Args:
                None
            Returns:
                None
        """
        # list of existing network ids
        self.network_ids = [row[0] for row in arcpy.da.SearchCursor(str(self.network_table), ["networkuid"])]
        # create empty dictionary of modes with prenetwork and postnetwork ids
        self.mode_id = {}
        with arcpy.da.SearchCursor(str(self.network_table), ["network_mode", "networkuid", "network_prepost", "network_edgeweight"]) as sc:
            for row in sc:
                # if the mode does not exist in the mode_id dictionary, add it with prenetwork and postnetwork keys
                if row[0] not in self.mode_id: 
                    self.mode_id[row[0]] = {"prenetwork":None, "postnetwork":None, "network_edgeweight":None}
                    self.mode_id[row[0]][row[2]] = row[1]
                    self.mode_id[row[0]]["network_edgeweight"] = row[3]
                else:
                    self.mode_id[row[0]][row[2]] = row[1]
                    self.mode_id[row[0]]["network_edgeweight"] = row[3]

    # NOTE: Called in build_networks class in TrACKIT.pyt though edge_weight parameter never specified
    def create_network(self, mode:str, rebuild:bool=True, edge_weight:str="fft") -> None:
        """
            Creates a network_class object for the network uid, mode, and both prenetwork/postnetwork then pickles the object and updates network table
            Args:
                mode(str): mode to create network for
                rebuild(bool): whether or not to rebuild a network that has already been built
                edge_weight(str): attribute name used to calculate distances for shortest path, default is free-flow travel time
            Returns:
                None
        """
        # check if there is a network to build from
        if arcpy.Exists(str(self.scenario_fgdb / self.schema_info["fc_name_integrated_network"])) is True:

            fft_mapping = {
                self.MODE_VEHICLE: self.schema_info["field_name_fft_vehicle"],
                self.MODE_TRUCK: self.schema_info["field_name_fft_truck"],
                self.MODE_PEDESTRIAN: self.schema_info["field_name_fft_ped"],
                self.MODE_BICYCLE: self.schema_info["field_name_fft_bike"],
                self.MODE_PREFERRED_BICYCLE: self.schema_info["field_name_fft_p_bike"],
                self.MODE_PREFERRED_PEDESTRIAN: self.schema_info["field_name_fft_ped"]
            }
            if edge_weight == "fft" and mode in fft_mapping:
                fc = str(self.scenario_fgdb / self.schema_info["fc_name_integrated_network"])
                bad_oids = [str(r[0]) for r in arcpy.da.SearchCursor(fc, ["OID@"], f"{mode} >= 1 And {fft_mapping[mode]} IS NULL")]
                if bad_oids:
                    arcpy.AddError(f"Network build failed. Found {len(bad_oids)} active '{mode}' links missing {fft_mapping[mode]} values. OIDs: {', '.join(bad_oids[:10])}...")
                    raise arcpy.ExecuteError

            arcpy.AddMessage(f"{str(self.scenario_fgdb / self.schema_info['fc_name_integrated_network'])} exists")
            # for both prenetwork and postnetwork
            for prenetwork in ["prenetwork", "postnetwork"]:
                # initialize mode_exists to false
                mode_exists = False
                # if the mode is already in the mode_id dictionary
                if mode in self.mode_id:
                    # get the network uid for that mode and prenetwork/postnetwork then set mode_exists to true
                    network_uid = self.mode_id[mode][prenetwork]
                    mode_exists = True
                else:
                    # otherwise, create a random new network uid
                    network_uid = random_id.create_random_id("NET", self.network_ids)
                    # add the mode to the mode_id dictionary with prenetwork and postnetwork keys
                    # TODO: Do we need to add a network_edgeweight key?
                    self.mode_id[mode] = {"prenetwork":None, "postnetwork":None}
                # if the network uid is still none, create a random new one
                if network_uid is None:
                    network_uid = random_id.create_random_id("NET", self.network_ids)
                    mode_exists = False
                arcpy.AddMessage(f"Mode exists = {mode_exists}")
                # if rebuild parameter is true or the mode does not exist
                if rebuild is True or mode_exists is False:
                    arcpy.AddMessage(network_uid)
                    # create a network class object with the mode, network uid, and the ways feature class
                    self.nc = network_class(mode, network_uid, self.scenario_fgdb / self.schema_info["fc_name_integrated_network"])
                    arcpy.AddMessage("building network")
                    # build the network with prenetwork true or false; assigns prenetwork to true or false
                    # TODO: Uses edge_weight default value of "fft" instead of passing in edge_weight variable
                    self.nc.build_network(prenetwork=="prenetwork")
                    # create a filename with the network uid, mode, and prenetwork/postnetwork
                    lbl_short = "pre" if prenetwork == "prenetwork" else "post"
                    filename = f"{network_uid}_{mode}_{lbl_short}.net"
                    arcpy.AddMessage(f"saving {prenetwork} network")
                    with open(self.scenario_folder / filename, 'wb') as f:
                        # save the network class object as a pickle file
                        pickle.dump(self.nc, f, protocol=4)
                    # if the mode did not exist before
                    if mode_exists is False:
                        with arcpy.da.InsertCursor(str(self.network_table), ["networkuid", "network_mode", "network_prepost", "network_edgeweight", "network_filename"]) as ic:
                            # insert a new row in the network table with the network uid, mode, prenetwork/postnetwork, edge weight, and filename
                            ic.insertRow([network_uid, mode, prenetwork, edge_weight, filename])
                            # add the network uid to the mode_id dictionary
                            self.mode_id[mode][prenetwork] = network_uid
                    # delete the network class object to free up memory
                    del self.nc
                else:
                    arcpy.AddMessage("Not rebuilding")
        else:
            # raise an exception if there is no ways feature class to build the network from
            raise Exception(f"{self.schema_info['fc_name_integrated_network']} does not exist in the scenario geodatabase.")

    # # TODO: Not called anywhere? Not needed?
    # def build_network_for_modes(self, modes:List[Any]=_TYPES_MODES, rebuild:bool=True, edge_weight:str="fft") -> None:
    #     """
    #         Runs create_network for each mode
    #         Args:
    #             modes(List): modes to create network for
    #             rebuild(bool): whether or not to rebuild a network that has already been built
    #             edge_weight(str): attribute name used to calculate distances for shortest path, default is free-flow travel time
    #         Returns:
    #             None
    #     """
    #     for m in modes:
    #         self.create_network(m)
            
    def load_network(self, mode:_TYPES_MODES, prenetwork=True) -> network_class:
        """
            Loads the network for the mode and prenetwork/postnetwork
        """
        # 1. The dictionary key still needs the full word
        dict_key = "prenetwork" if prenetwork else "postnetwork"
        
        # 2. The filename needs the short word
        lbl_short = "pre" if prenetwork else "post"

        # 3. Construct filename using both
        filename = f"{self.mode_id[mode][dict_key]}_{mode}_{lbl_short}.net"
        
        arcpy.AddMessage(f"Loading {filename}")
        network = None
        with open(self.scenario_folder / filename, 'rb') as f:
            network = pickle.load(f)
        return network

    def get_matched_nodes(self) -> None:
        """
            Creates set of node POI IDs
            Args:
                None
            Returns:
                None
        """
        self.set_matched_osmids = None
        # find all node poi ids that are not origins
        matched_osmids = [row[0] for row in arcpy.da.SearchCursor(str(self.scenario_fgdb / self.schema_info["fc_matched_poi_table"]), self.schema_info["field_name_poi_nodeid"], "poi_type <> 'Origins'")]
        # TODO: The set_matched_osmids attribute is never used anywhere?
        self.set_matched_osmids = set(matched_osmids)

    def get_filtered_network_node_ids(self, mode:_TYPES_MODES, prenetwork:bool, limit:float) -> List[Any]:
        """
            Creates a unique list of destination network node IDs filtered down based on modal radius limits assigned by user;
            This helps filter down the size of the resulting distances matrices prior to report analysis to only include destination 
                network nodes that could reaonably be reached within a user defined travel distance
            Args:
                mode(str): mode to create network for
                prenetwork(bool): prenetwork or postnetwork
                limit(float): search distance in meters
            Returns:
                List of destination network node IDs
        """
        # create corresponding where clause for search cursor
        if prenetwork is True:
            wc = f"{mode} = 1 and {self.schema_info['field_name_prenetwork']} = 1"
        elif prenetwork is False:
            wc = f"{mode} = 1 and {self.schema_info['field_name_postnetwork']} = 1"

        #determine origin type user has selected to buffer when filtering network nodes
        scenario_table = str(self.project_fgdb / self.schema_info["fc_scenario_table"])
        if arcpy.Exists(str(scenario_table)):
            with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_origin_type"]]) as sc:
                for row in sc:
                    if row[0] == str(self.scenario_name):
                        orig_type = row[1]

        census_fc = str(self.scenario_fgdb / self.schema_info["fc_name_census_block_prj"])
        custom_poly_fc = str(self.scenario_fgdb / self.schema_info["fc_name_custom_origin_polygons"])
        if orig_type == "Census Blocks" and arcpy.Exists(census_fc):
            origins_fc = census_fc
        elif orig_type == "Custom Polygons" and arcpy.Exists(custom_poly_fc):
            origins_fc = custom_poly_fc
        else:
            origins_fc = str(self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"])

        # create selection using the distance threshold from all origins
        lyr = arcpy.management.SelectLayerByLocation(
                in_layer=str(self.scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]),
                overlap_type="WITHIN_A_DISTANCE",
                select_features=str(origins_fc),
                search_distance=f"{limit} Meters",
                selection_type="NEW_SELECTION",
                invert_spatial_relationship="NOT_INVERT"
            ).getOutput(0)
        
        # collect all node IDs within selection
        modeosmids = [row[0] for row in arcpy.da.SearchCursor(lyr, [self.schema_info["field_name_node_id"]], wc)]

        return list(set(modeosmids))

    def get_origin_ids(self) -> List[Any]:
        """
            Creates unique list of origin IDs
            Args:
                None
            Returns:
                List of origin OSM IDs
        """
        return [row[0] for row in arcpy.da.SearchCursor(str(self.scenario_fgdb / self.schema_info["fc_name_origin_nodes"]), [self.schema_info["field_name_origin_id"]])]
    
    # NOTE: Called in accessibility_distances class in TrACKIT.pyt
    # TODO: Figure out conversion of limit to fft? Incorporate weightedby parameter?
    def process_distance_calculations(self, mode:str, limit_miles:float, weightedby:str="fft") -> None:
        """
            Creates unique list of destination IDs
            Args:
                mode(str): mode to create network for
                limit_miles(float): search distance in miles
                weightedby(str): edge weight for distance calculations
            Returns:
                None
        """
        # get origin OSM IDs
        origin_osmids = self.get_origin_ids()
        arcpy.AddMessage(f"Number of origins: {len(origin_osmids)}")
        # find matched POI node IDs
        self.get_matched_nodes()
        # calculate search distance in meters
        limit_meters = None
        if limit_miles is not None:
            limit_meters = limit_miles * 1609.34
        # initialize the results dictionary for the mode if it does not exist
        if mode not in self.results:
            self.results[mode] = {"prenetwork":None, "postnetwork":None}
        # for both prenetwork and postnetwork
        for prenetwork in (True, False):
            lbl = "pre" if prenetwork else "post"
            # get filtered network node list based on mode-specific travel distance thresholds assigned by user
            destination_osmids = self.get_filtered_network_node_ids(mode, prenetwork, limit_meters)
            arcpy.AddMessage(f"Number of destinations: {len(destination_osmids)}")
            if mode in self.mode_id:
                # load the network for the mode and prenetwork/postnetwork
                self.network = self.load_network(mode, prenetwork)
                filename = self.scenario_folder / f"{self.scenario_name}_{mode}_{lbl}_dist_matrix.dist"
                # calculate the distances from the origins to the destinations using the network class method
                self.network.distance_origins_to_destinations(origin_osmids, destination_osmids, filename)

     