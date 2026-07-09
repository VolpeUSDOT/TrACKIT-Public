import requests
import http.client
from pathlib import Path
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
from arcgis.geometry.filters import intersects
import arcpy
import json
import yaml
import time
from messenger import custTypes
from messenger import custMessenger
from managers import settingsManager
class downloader(settingsManager):
    def __init__(self, projectFolder:Path, messages:custMessenger = None):
        """
            Parent class for downloading data
            Args:
                projectFolder (Path): folder where the project data is written.
            Returns:
                downloader class object or child of the processor class.
        """
        super().__init__(projectFolder, messages, ignore_centroid=True)
        self.root_url = None
        self.timeout = 305 
        self.timeout_increase = 60
        self.max_retries = 5
        self.pauses = 20
        self.chunksize = 65536#2*1024


    def download_data_bbox(self, minlat:float,
                              minlong:float,
                              maxlat:float,
                              maxlong:float):
        raise NotImplementedError


    def download_data_center_point(self, latitude:float, longitude:float):
        raise NotImplementedError

class osm_overpass_ways(downloader):

    def __init__(self, projectFolder:Path, messages:custMessenger):
        """
            Download ways and points of interest from OpenStreetMap through the overpass-api.
            Args:
                projectFolder (Path): folder where the project data is written.
            Returns:
                osm_overpass object
        """
        super().__init__(projectFolder, messages)
        self.root_url = "http://overpass-api.de/api/interpreter"

    def download_data_bbox(self, minlat:float,
                              minlong:float,
                              maxlat:float,
                              maxlong:float,
                              dataName:str, factoryCode=None)->Path:
        """
            Download OSM xml file from overpass API
            Arguments:
                minlat (float): lower left latitude
                minlong (float): lower left longitude
                maxlat (float): upperright latitude
                maxlong (float): upper right longitude
                dataName (str): name to save the file
            Returns:
                tuple (Path, Path): path to the osm ways and the osm poi file in the project folder
        """
        #latdiff = round(maxlat - minlat,0)
        #latmiles = latdiff * 69.1
        #self.messages.send_message(f" latitude estimated miles {latmiles}")


        ways_query = """
            [out:xml][timeout:300];
            (
            node({0},{1},{2},{3});
            way["highway"~".*"]["highway"!="service"]["highway"!="construction"]["highway"!="proposed"]({0},{1},{2},{3});
            );
            (._;>;);
            out body;
            """
        


        session = requests.Session()
        ctimeout = self.timeout
        failedAfterThree = True

        for attempt in range(self.max_retries):
            attemptPause = self.pauses * 2**attempt
            try:
                response = session.get(self.root_url, 
                                params={'data': ways_query.format(minlat,minlong,maxlat,maxlong)}, stream=True, timeout=(10,ctimeout),
                                headers = {"User-Agent": "TrACKIT Tool"})
                response.raise_for_status()
                self.messages.send_message("Streaming Ways download from Overpass.")
                self.messages.set_progressor("Downloading ways from Overpass...",
                    0, 100, 1)
                try:
                    with open(self.project_folder / f"{dataName}_ways.osm", "wb") as f:
                        tracking_progress = 1
                        for data in response.iter_content(chunk_size=self.chunksize):
                            self.messages.set_progressor_position(tracking_progress)
                            f.write(data)
                            tracking_progress += 1
                            if tracking_progress == 100:
                                tracking_progress = 1
                            if arcpy.env.isCancelled:
                                # Raising an exception will break the script 
                                # immediately from wherever it is currently executing.
                                raise Exception("User Cancelled via ArcGIS UI")
                    del response
                    self.messages.reset_progressor()
                    failedAfterThree = False
                    break
                except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, http.client.IncompleteRead) as e:
                    self.messages.send_message(f"Stream broken mid-download: {e}")
                    if arcpy.env.isCancelled:
                        # Raising an exception will break the script 
                        # immediately from wherever it is currently executing.
                        raise Exception("User Cancelled via ArcGIS UI")
                    continue

                #
                
            except requests.exceptions.Timeout:
                self.messages.send_message("Timeout on ways for attempt.")
            except http.client.IncompleteRead as e:
                self.messages.send_message("Error reading the download stream. Attempting again.")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    
                    self.messages.send_message(f"Attempt failed, pausing {attemptPause}.")
                    time.sleep(attemptPause)
                elif e.response.status_code == 504:
                    self.messages.send_message(f"HTTP Error {e.response.status_code}")
                    time.sleep(attemptPause)
                    ctimeout += self.timeout_increase
                else:
                    self.messages.send_message(f"Ways - HTTP Error {e.response.status_code}: {e}")
            self.messages.send_message("Pausing to not overload servers...", custTypes.INFORMATION)
            time.sleep(attemptPause)
            if arcpy.env.isCancelled:
                # Raising an exception will break the script 
                # immediately from wherever it is currently executing.
                raise Exception("User Cancelled via ArcGIS UI")

        session.close()

        if failedAfterThree is True:
            return None
        
        osm_ways_path = self.project_folder / f"{dataName}_ways.osm"
        return osm_ways_path
    

class osm_overpass_poi(downloader):

    def __init__(self, projectFolder:Path, messages:custMessenger):
        """
            Download ways and points of interest from OpenStreetMap through the overpass-api.
            Args:
                projectFolder (Path): folder where the project data is written.
            Returns:
                osm_overpass object
        """
        super().__init__(projectFolder, messages)
        self.root_url = "http://overpass-api.de/api/interpreter"

    def download_data_bbox(self, minlat:float,
                              minlong:float,
                              maxlat:float,
                              maxlong:float,
                              dataName:str, factoryCode=None)->Path:
        """
            Download OSM xml file from overpass API
            Arguments:
                minlat (float): lower left latitude
                minlong (float): lower left longitude
                maxlat (float): upperright latitude
                maxlong (float): upper right longitude
                dataName (str): name to save the file
            Returns:
                tuple (Path, Path): path to the osm ways and the osm poi file in the project folder
        """
        #latdiff = round(maxlat - minlat,0)
        #latmiles = latdiff * 69.1
        #self.messages.send_message(f" latitude estimated miles {latmiles}")


        
        poi_query = """
            [out:xml][timeout:300];
            nwr[~".*"~"^({4})$"][!highway]({0},{1},{2},{3});
            (._;>;);
            out body;
            """
        # nwr — short for node/way/relation
        # [".*""^({4})$"] — this is a tag key/value regex filter:
            # Here the key regex is ".*" (any key), and the value regex is "^({4})$" — so it matches any tag value that exactly matches one of the alternatives provided in placeholder {4} (typically a pipe-separated list like "amenity|shop|tourism").
        # [!highway] — exclude elements that have any highway tag (so POIs that are not highways).
        # ({0},{1},{2},{3}); — restrict to elements inside the specified bounding box.
        # (._;>;); and out body; — same recursion and output as above (include member nodes and output XML).

        session = requests.Session()
        ctimeout = self.timeout
        failedAfterThree = True
        ctimeout = self.timeout
        for attempt in range(self.max_retries):
            attemptPause = self.pauses * 2**attempt
            try:
                response = session.get(self.root_url, 
                                        params={'data': poi_query.format(minlat,minlong,maxlat,maxlong,self.settings_info["poi_values_as_string"])},
                                        stream=True, timeout=(10,ctimeout),
                                        headers = {"User-Agent": "TrACKIT Tool"})
                response.raise_for_status()
                self.messages.send_message("Streaming POI download from Overpass.")
                self.messages.set_progressor("Downloading POI from Overpass...",
                    0, 100, 1)
                try:
                    with open(self.project_folder / f"{dataName}_poi.osm", "wb") as f:
                        tracking_progress = 1
                        
                        for data in response.iter_content(chunk_size=self.chunksize):
                                self.messages.set_progressor_position(tracking_progress)
                                f.write(data)
                                tracking_progress += 1
                                if tracking_progress == 100:
                                    tracking_progress = 1
                        if arcpy.env.isCancelled:
                            # Raising an exception will break the script 
                            # immediately from wherever it is currently executing.
                            raise Exception("User Cancelled via ArcGIS UI")
                    self.messages.set_progressor_position(100)
                    self.messages.reset_progressor()
                    del response
                    failedAfterThree = False
                    break
                except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, http.client.IncompleteRead) as e:
                    self.messages.send_message(f"Stream broken mid-download: {e}")
                    continue


                
            except requests.exceptions.Timeout:
                self.messages.send_message("Timeout on POI for attempt.")
            except http.client.IncompleteRead as e:
                self.messages.send_message("Error reading the download stream. Attempting again.")
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    self.messages.send_message(f"Attempt failed, pausing {attemptPause}.")
                    time.sleep(attemptPause)
                elif e.response.status_code == 504:
                    self.messages.send_message(f"POI - HTTP Error {e.response.status_code}")
                    time.sleep(attemptPause)
                    ctimeout += self.timeout_increase
                else:
                    self.messages.send_message(f"HTTP Error {e.response.status_code}: {e}")
            self.messages.send_message("Pausing to not overload servers...", custTypes.INFORMATION)
            time.sleep(attemptPause)
            if arcpy.env.isCancelled:
                # Raising an exception will break the script 
                # immediately from wherever it is currently executing.
                raise Exception("User Cancelled via ArcGIS UI")
        
        session.close()

        if failedAfterThree is True:
            return None


        osm_poi_path = self.project_folder / f"{dataName}_poi.osm"
        return osm_poi_path
    
class osm_overpass_water(downloader):

    def __init__(self, projectFolder:Path, messages:custMessenger):
        """
            Download ways and points of interest from OpenStreetMap through the overpass-api.
            Args:
                projectFolder (Path): folder where the project data is written.
            Returns:
                osm_overpass object
        """
        super().__init__(projectFolder, messages)
        self.root_url = "http://overpass-api.de/api/interpreter"

    def download_data_bbox(self, minlat:float,
                              minlong:float,
                              maxlat:float,
                              maxlong:float,
                              dataName:str, factoryCode=None)->Path:
        """
            Download OSM xml file from overpass API
            Arguments:
                minlat (float): lower left latitude
                minlong (float): lower left longitude
                maxlat (float): upperright latitude
                maxlong (float): upper right longitude
                dataName (str): name to save the file
            Returns:
                tuple (Path, Path): path to the osm ways and the osm poi file in the project folder
        """

        water_query = """
            [out:xml][timeout:300];
            (
                way["natural"="water"]({0},{1},{2},{3});
                way["natural"="bay"]({0},{1},{2},{3});
                way["water"~"lake|pond|reservoir|river"]({0},{1},{2},{3});
                way["waterway"="riverbank"]({0},{1},{2},{3});
                
                relation["natural"="water"]({0},{1},{2},{3});
                relation["natural"="bay"]({0},{1},{2},{3});
                relation["water"~"lake|pond|reservoir|river"]({0},{1},{2},{3});
                relation["waterway"="riverbank"]({0},{1},{2},{3});
            );
            (._;>;);
            out body;
            """
        
        session = requests.Session()
        ctimeout = self.timeout
        failedAfterThree = True
        for attempt in range(self.max_retries):
            attemptPause = self.pauses * 2**attempt
            try:
                response = session.get(self.root_url, 
                                        params={'data': water_query.format(minlat,minlong,maxlat,maxlong)}, stream=True, timeout=(10,ctimeout),
                                        headers = {"User-Agent": "TrACKIT Tool"})
                response.raise_for_status()
                self.messages.send_message("Streaming Water download from Overpass.")
                self.messages.set_progressor("Downloading water from Overpass...",
                    0, 100, 1)
                try:
                    with open(self.project_folder / f"{dataName}_water.osm", "wb") as f:
                        tracking_progress = 1
                        for data in response.iter_content(chunk_size=self.chunksize):
                            self.messages.set_progressor_position(tracking_progress)
                            f.write(data)
                            tracking_progress += 1
                            if tracking_progress == 100:
                                tracking_progress = 1
                        self.messages.set_progressor_position(100)
                        if arcpy.env.isCancelled:
                            # Raising an exception will break the script 
                            # immediately from wherever it is currently executing.
                            raise Exception("User Cancelled via ArcGIS UI")
                    del response
                    self.messages.reset_progressor()
                    failedAfterThree = False
                    break
                except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, http.client.IncompleteRead) as e:
                    self.messages.send_message(f"Stream broken mid-download: {e}")
                    continue

            except requests.exceptions.Timeout:
                self.messages.send_message("Timeout on POI for attempt.")
            except http.client.IncompleteRead as e:
                self.messages.send_message("Error reading the download stream. Attempting again.")
                time.sleep(attemptPause)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    self.messages.send_message(f"Attempt failed, pausing {attemptPause}.")
                    time.sleep(attemptPause)
                elif e.response.status_code == 504:
                    self.messages.send_message(f"Water - HTTP Error {e.response.status_code}")
                    time.sleep(attemptPause)
                    ctimeout += self.timeout_increase
                else:
                    self.messages.send_message(f"HTTP Error {e.response.status_code}: {e}")
            self.messages.send_message("Pausing to not overload servers...", custTypes.INFORMATION)
            time.sleep(attemptPause)
            if arcpy.env.isCancelled:
                # Raising an exception will break the script 
                # immediately from wherever it is currently executing.
                raise Exception("User Cancelled via ArcGIS UI")

        session.close()

        if failedAfterThree is True:
            return None
        
        return self.project_folder / f"{dataName}_water.osm"

    
class census_blocks(downloader):
    def __init__(self, projectFolder:Path, messages:custMessenger):
        """
            Download Census Blocks through TIGERWeb.
            
            Args:
                projectFolder (Path): folder where the project data is written.
            Returns:
                osm_overpass object
        """
        super().__init__(projectFolder, messages)
        self.root_url = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/12"
    

    
    def download_data_bbox(self,minlat:float,
                              minlong:float,
                              maxlat:float,
                              maxlong:float,
                              fgdb:Path,factoryCode:int = None):
        """
            Download Census Block Geometry from TIGERWeb
            Arguments:
                minlat (float): lower left latitude
                minlong (float): lower left longitude
                maxlat (float): upperright latitude
                maxlong (float): upper right longitude
                fgdb (Path): path to the file geodatabase to save the census blocks
            Returns:
                Path: path to the feature class for the Census Blocks
        """
        #sr = arcpy.SpatialReference(4326)
        #layersr = arcpy.SpatialReference(102100) #web mercator
        #ll = arcpy.PointGeometry(arcpy.Point(minlong, minlat), sr).projectAs(layersr)
        #ur = arcpy.PointGeometry(arcpy.Point(maxlong, maxlat), sr).projectAs(layersr)
        retain_fields = self.settings_info.get("census_fields_to_keep", None)

        if retain_fields is None:
            retain_fields = ["GEOID", "POP100", "HU100"]
        tigerweb_layer = FeatureLayer(self.root_url)

        # Create an extent object (or define as a dictionary for the API query)
        # You might need to adjust based on the coordinate system of the TIGERweb service
        #query_extent = {"xmin": ll.centroid.X, "ymin": ll.centroid.Y, "xmax": ur.centroid.X, "ymax": ur.centroid.Y, "spatialReference": {"wkid": 102100}} # Example spatial reference (WGS 84)
        query_extent = {"xmin": minlong, "ymin": minlat, "xmax": maxlong, "ymax": maxlat, "spatialReference": {"wkid": 4326}} 
        arcpy.AddMessage(f"Query Extent: {query_extent}")
        # Build the query
        #query_params = {"geometry": query_extent, "spatialRelationship": "esriSpatialRelIntersects"} # Adjust spatial relationship as needed
        #arcpy.AddMessage(f"Query Parameters: {query_params}")

        query_filter = intersects(query_extent, sr=4326)
        # Execute the query
        max_attempts = 3
        backoff = 1.0
        feature_set = None
        for attempt in range(1, max_attempts + 1):
            arcpy.AddMessage(f"Attempt {attempt} to query TIGERweb")
            try:
                #feature_set = tigerweb_layer.query(**query_params)
                feature_set = tigerweb_layer.query(geometry_filter=query_filter, out_fields=retain_fields)
                break
            except Exception as e:
                self.messages.send_message(f"tigerweb query attempt {attempt} failed: {e}", custTypes.WARNING)
                if attempt == max_attempts:
                    self.messages.send_message("Failed to download TIGER data after retries — continuing without it.", custTypes.WARNING)
                    feature_set = None
                else:
                    time.sleep(backoff)
                    backoff *= 2.0
            if arcpy.env.isCancelled:
                # Raising an exception will break the script 
                # immediately from wherever it is currently executing.
                raise Exception("User Cancelled via ArcGIS UI")

        # Process the results (e.g., save to a feature class)
        fcname = self.schema_info["fc_name_census_block"]
        fcname_prj = self.schema_info["fc_name_census_block_prj"]
        arcpy.SetProgressorLabel("Saving census blocks from TIGERWeb")
        feature_set.save(str(fgdb), fcname)
        returnPath = fgdb / fcname
        self.messages.send_message("Altering population field names.")
        arcpy.management.AlterField(str(returnPath), "POP100", self.schema_info["field_name_population"], self.schema_info["field_name_population"])
        arcpy.management.AlterField(str(returnPath), "HU100", self.schema_info["field_name_housing_units"], self.schema_info["field_name_housing_units"], )
        if factoryCode is not None:
            self.messages.send_message(f"Projecting to {factoryCode}.")
            returnPath = arcpy.management.Project(str(returnPath), str(fgdb/fcname_prj), arcpy.SpatialReference(factoryCode)).getOutput(0)
            returnPath = Path(returnPath)


        
        return returnPath