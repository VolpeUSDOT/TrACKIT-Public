################################
#Primary Authors: Josiah Blackwell-Lipkind, David S. Lamb, Alison Link, Ian Berg, Kevin Zhang, Sophie Abo, and Scott B. Smith
#Developed by the USDOT Volpe Center 
#Sponsored by FHWA
##################################

#IMPORTS
import arcpy
from pathlib import Path
import maintenance
import random
from importlib import reload
import sys
import traceback


#GLOBALS
TOOLBOX_VERSION = "Prerelease"
OSM_LICENSE = "OpenStreetMap® is open data, licensed under the Open Data Commons Open Database License (ODbL) by the OpenStreetMap Foundation (OSMF).\nYou are free to copy, distribute, transmit and adapt our data, as long as you credit OpenStreetMap and its contributors.\nIf you alter or build upon our data, you may distribute the result only under the same licence.\nThe full legal code explains your rights and responsibilities."
PROJECT_FILE = Path(__file__).parents[0] / "projects.json"


#TOOLBOX
class Toolbox:
    def __init__(self):
        """
        Initialize the Toolbox used by the ArcGIS Python toolbox framework.

        This class defines the main container for all tools included in the TrACKIT toolbox.
        It sets the toolbox label, alias, and registers all available tools.

        Attributes:
            label (str): The display name for the toolbox shown in ArcGIS.
            alias (str): Internal identifier for the toolbox.
            tools (list): List of tool classes instantiated by ArcGIS for use within the toolbox.

        Usage:
            This class is instantiated by ArcGIS Pro when the toolbox (.pyt) is loaded.
            No parameters required.
        """

        self.label = "TrACKIT"
        self.alias = "toolbox"

        # List of tool classes associated with this toolbox
        self.tools = [osm_download, generate_scenario_networks, osm_ways_data, integrate_changes_data,osm_poi_data, custom_poi_data,
                      match_to_nodes_data, centroid_connectors, build_networks, accessibility_distances,
                      accessibility_measures_cumulative, accessibility_measures_dual, path_checker, manage_project,
                      travel_shed, report, manual_edits, redownload_osmdata]
        #Remove for V1: travel_shed_density, direction_roses, reachable_nodes_summary_report, change_settings  
        if PROJECT_FILE.exists() is False:
            maintenance.package_project.create_project_file([], PROJECT_FILE)

def raiseIfCancelled(frame, event, arg):
    if arcpy.env.isCancelled:
        # Raising an exception will break the script 
        # immediately from wherever it is currently executing.
        raise Exception("User Cancelled via ArcGIS UI")
    return raiseIfCancelled
    


def load_schema():
    """
        Loads the settings schema file, stores as schema _info variable
        Args:
            None
        Returns:
            None
    """
    import yaml
    file_path = Path(__file__).parents[0]
    with open(file_path / 'schema.yaml', 'r') as f:
        schema_info = yaml.load(f, Loader=yaml.Loader)
    return schema_info

def load_colors():
    import json
    file_path = Path(__file__).parents[0]
    with open(file_path / 'colors.json', 'r') as file:
        colors = json.load(file)
    return colors

def load_json_settings():
    """
        Loads the settings file, stores as settings_info variable
        Args:
            None
        Returns:
            None
    """
    import json
    file_path = Path(__file__).parents[0]
    with open(file_path / 'settings.json', 'r', encoding='UTF-8') as file:
        settings_info = json.load(file)
    return settings_info

#TOOLS  
class osm_download:
    """
    Tool to create project folder, geodatabase, and download OpenStreetMap (OSM) data and census blocks.

    This tool automates downloading and organizing base geographic datasets needed for travel
    accessibility analysis. It performs these steps:

    - Creates a project folder and file geodatabase.
    - Downloads OSM 'ways' XML data and POI (Points of Interest) XML.
    - Downloads census blocks around a defined center point with specified radius.
    - Writes and processes spatial data into appropriate feature classes and tables.

    Parameters (via getParameterInfo):
        out_directory (DEFolder): Directory path where the project folder and geodatabase will be created.
        name_for_file (GPString): Unique project name (no spaces) used as folder prefix.
        dataExtent (GPDouble): Radius (in miles) from project center to define area of data download.
        slat (GPString): Latitude coordinate of project center.
        wlong (GPString): Longitude coordinate of project center.
        license_info (GPString, Optional): OpenStreetMap data license information text to be displayed.

    Side Effects:
        - Creates folders and geodatabases on disk.
        - Downloads data via network requests, which may take several minutes depending on study area size.
        - Writes log and message information to ArcGIS Pro geoprocessing messages.

    Notes:
        - The coordinate reference system used throughout is WGS84 (EPSG:4326).
        - Network download may be interrupted by connectivity issues; rerun if needed.
        - The tool includes warnings about data download time for large areas.

    Usage Example:
        Run the tool in ArcGIS Pro, specify project folder, name, and center coordinates,
        then wait for data download to complete.

    Raises:
        IOError: When network download or file writing fails.

    """
    def __init__(self):
        """
        Initialize tool label, description, and category for ArcGIS tool registration.
        """
        self.label = "1A. Download Base OSM Data"
        self.description = ""
        self.category = "1 - Create Base Dataset"
        self.schema_info = load_schema()
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


        
    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        self.proj = arcpy.mp.ArcGISProject("CURRENT")
        self.sr = arcpy.SpatialReference(4326)
        try:
            self.m = self.proj.activeMap
            mapExtents=self.m.defaultCamera.getExtent()
            geoextents = mapExtents.projectAs(self.sr)
            centroid_x = (geoextents.XMin + geoextents.XMax) / 2
            centroid_y = (geoextents.YMin + geoextents.YMax) / 2
        except:
            centroid_x = 0
            centroid_y = 0

        directory = arcpy.Parameter(
            displayName="Place Project Folder Here",
            name="out_directory",
            datatype="DEFolder",
            parameterType="Required",
            direction="Input")
        params.append(directory)
        
        nameforfile = arcpy.Parameter(
            displayName="Project Name (No Spaces)",
            name="name_for_file",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(nameforfile)

        dataExtent = arcpy.Parameter(
            displayName="Download Extent (Miles from Project Center)",
            name="dataExtent",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        dataExtent.value = 26.5
        params.append(dataExtent)

        slat = arcpy.Parameter(
            displayName="Download Center Latitude",
            name="slat",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(slat)

        wlong = arcpy.Parameter(
            displayName="Download Center Longitude",
            name="wlong",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(wlong)

        license_info = arcpy.Parameter(
            displayName="Use of OpenStreetMap Data",
            name="license_info",
            datatype="GPString",
            parameterType="Optional",
            direction="Output")
        license_info.value = OSM_LICENSE
        params.append(license_info)
        # nlat = arcpy.Parameter(
        #     displayName="Northern Latitude",
        #     name="nlat",
        #     datatype="GPString",
        #     parameterType="Required",
        #     direction="Input",
        #     category="Study Area")
        # nlat.value = geoextents.YMax
        # params.append(nlat)

        # elong = arcpy.Parameter(
        #     displayName="Eastern Longitude",
        #     name="elong",
        #     datatype="GPString",
        #     parameterType="Required",
        #     direction="Input",
        #     category="Study Area")
        # elong.value = geoextents.XMax
        # params.append(elong)


    
        return params
    

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        """Modify the values and properties of parameters before internal
        validation is performed.  This method is called whenever a parameter
        has been changed."""

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[1].altered:
            if parameters[1].valueAsText in self.projects:
                parameters[1].setErrorMessage(f"The project name {parameters[1].valueAsText} already exists. Rename this Project or using the Remove Project tool to delete the existing Project of the same name.")

            if parameters[1].valueAsText and parameters[0].valueAsText:
                outFolder = str(Path(parameters[0].valueAsText) / f"{parameters[1].valueAsText}_project")
                warnings = 0
                warningMessage = "Potential issues with your output folder location.\n"
                if "-" in outFolder:
                    warningMessage += "The path contains a dash.\n"
                    warnings += 1
                if " " in outFolder:
                    warningMessage += "The path contains a space.\n"
                    warnings += 1
                if "/" in outFolder:
                    warningMessage += "The path contains a slash.\n"
                    warnings += 1
                if len(str(outFolder)) + 85 > 225:
                    warningMessage += "The path to the output folder is likely too long. This can cause problems when running the tool. Choose a higher level folder.\n"
                    warnings += 1
                if warnings > 0:
                    parameters[1].setWarningMessage(warningMessage)

        return

        return

    def execute(self, parameters, messages):
        """The source code of the tool."""
        
        import data_downloader
        import data_osm_processor
        from messenger import custMessenger
        from messenger import custTypes
        from static_tools import helper_functions
        import managers
        import time
        reload(data_downloader)
        reload(data_osm_processor)
        reload(managers)
        try:
            project = {"name":None, "path":None, "latitude":None,
                    "longitude":None, "radius":None, "utmepsg":None}

            outputPath = Path(parameters[0].valueAsText)
            outName = parameters[1].valueAsText
            if outName.endswith("_project"):
                outName = outName.replace("_project", "")
            project["name"] = outName

            if outName in self.projects:
                arcpy.AddWarning(f"Existing project names: {','.join(list(self.projects.keys()))}")
                arcpy.AddError(f"The project name {outName} already exists.")
                return

            radius_destination = float(parameters[2].value)
            centroid_y = float(parameters[3].value)
            centroid_x = float(parameters[4].value)
            arcpy.AddMessage((centroid_x, centroid_y))
            project["latitude"] = centroid_y
            project["longitude"] = centroid_x
            project["radius"] = radius_destination

            if radius_destination > 5:
                arcpy.AddMessage("Note: Downloading OpenStreetMap data will take several minutes with large study areas.")
            else:
                pass

            if centroid_y > 90 or centroid_y < -90:
                arcpy.AddError("Latitude must be between -90 and 90")
                return
            if centroid_x > 180 or centroid_x < -180:
                arcpy.AddError("Longitude must be between -180 and 180")
                return 
            if centroid_y > 65 or centroid_y < -65:
                arcpy.AddWarning("Warning: Latitude is very northernly/southernly. You may want to double check your lat/long.")        
            if centroid_x > 165 or centroid_x < -165:
                arcpy.AddWarning("Warning: Longitude is very easterly/westerly. You may want to double check your lat/long.")


            messages = custMessenger(custTypes.ARCPYMESSAGE)
            sr = helper_functions.get_wgs84_sr()
            utm_sr = helper_functions.get_utm_spatialreference(centroid_y, centroid_x, returnSR=True)
            project["utmepsg"] = utm_sr.factoryCode
            ll_lat, ll_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, -1*radius_destination, -1*radius_destination)
            ur_lat, ur_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, radius_destination, radius_destination)
            #centroid_point_utm = arcpy.PointGeometry(arcpy.Point(centroid_x, centroid_y), sr).projectAs(utm_sr)
            #buffer_dist = radius_destination * 1609.34
            #buffer_centroid = centroid_point_utm.buffer(buffer_dist).projectAs(sr)
            #buffer_ext = buffer_centroid.extent

            projectFolder = outputPath / f"{outName}_project"
            projectFolder.mkdir(exist_ok=True)
            project["path"] = str(projectFolder)
            fgdb = helper_functions.drop_add_fgdb(projectFolder, f"{outName}_data.gdb")

            dl = data_downloader.osm_overpass_ways(projectFolder, messages)
            waysxml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)


            dl = data_downloader.osm_overpass_poi(projectFolder, messages)
            poixml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)
            

            project_polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(ll_long, ll_lat),
                                                arcpy.Point(ur_long, ll_lat),
                                                arcpy.Point(ur_long, ur_lat),
                                                arcpy.Point(ll_long, ur_lat),
                                                arcpy.Point(ll_long, ll_lat),]), spatial_reference=arcpy.SpatialReference(4326))

            #buffer_dist = radius_origin * 1609.34
            #buffer_centroid = centroid_point_utm.buffer(buffer_dist).projectAs(sr)
            #buffer_ext = buffer_centroid.extent

            arcpy.AddMessage("Create project coverage area feature class.")
            proj_coverage_area_fc = helper_functions.drop_add_featureclass(fgdb, self.schema_info["fc_name_project_coverage_area"], "POLYGON", sr)
            helper_functions.drop_add_field(str(proj_coverage_area_fc), self.schema_info["field_name_project_name"], "TEXT",field_alias="Project Name")
            helper_functions.drop_add_field(str(proj_coverage_area_fc), self.schema_info["field_name_utm"], "LONG",field_alias="EPSG Code UTM Zone")
            helper_functions.drop_add_field(str(proj_coverage_area_fc), self.schema_info["field_name_radius_dest"], "DOUBLE",field_alias="Radius for All Destinations")
            helper_functions.drop_add_field(str(proj_coverage_area_fc), self.schema_info["field_name_tool_version"], "TEXT", field_alias="Database Version for Tool")
            with arcpy.da.InsertCursor(str(proj_coverage_area_fc), ["SHAPE@", self.schema_info["field_name_project_name"], self.schema_info["field_name_utm"], self.schema_info["field_name_radius_dest"], self.schema_info["field_name_tool_version"]]) as ic:
                ic.insertRow([project_polygon, outName, utm_sr.factoryCode, radius_destination, TOOLBOX_VERSION])

            arcpy.AddMessage("Create project centroid feature class.")
            pcfc = helper_functions.drop_add_featureclass(fgdb, self.schema_info["fc_name_project_centroid"], "POINT", sr)
            helper_functions.drop_add_field(str(pcfc), self.schema_info["field_name_project_name"], "TEXT",field_alias="Project Name")
            helper_functions.drop_add_field(str(pcfc), self.schema_info["field_name_utm"], "LONG",field_alias="EPSG Code UTM Zone")
            helper_functions.drop_add_field(str(pcfc), self.schema_info["field_name_radius_dest"], "DOUBLE",field_alias="Radius for All Destinations")
            helper_functions.drop_add_field(str(pcfc), self.schema_info["field_name_tool_version"], "TEXT", field_alias="Database Version for Tool")
            with arcpy.da.InsertCursor(str(pcfc), ["SHAPE@", self.schema_info["field_name_project_name"], self.schema_info["field_name_utm"], self.schema_info["field_name_radius_dest"], self.schema_info["field_name_tool_version"]]) as ic:
                ic.insertRow([arcpy.PointGeometry(arcpy.Point(centroid_x, centroid_y), sr), outName, utm_sr.factoryCode, radius_destination, TOOLBOX_VERSION])
            time.sleep(45)
            arcpy.AddMessage("Creating waterbodies....")
            
            dl = data_downloader.osm_overpass_water(projectFolder, messages)
            waterxml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)
            oneMB = 1048576
            if None in [waterxml, poixml, waysxml]:
                arcpy.AddWarning("Downloading file failure.")
                arcpy.AddWarning("##################################################")
                arcpy.AddWarning("Problems:")
                if waterxml is None:
                    arcpy.AddWarning(f"Downloading the water features OSM data failed. The file may be empty: {outName}_water.osm.")
                if poixml is None:
                    arcpy.AddWarning(f"Downloading the POI OSM data failed. The file may be empty: {outName}_poi.osm")
                if waysxml is None:
                    arcpy.AddWarning(f"Downloading the water features OSM data failed: {outName}_ways.osm")


                arcpy.AddWarning("Solutions:")
                arcpy.AddWarning("This tool uses the Overpass API, and sometimes their servers are overwhelmed by requests for OSM data. This may cause the tool to fail. Here are some possible steps to take.")
                arcpy.AddWarning("1. If the project was successfully created, use Maintenance -> Redownload OSM Data to attempt to download the OSM data. If the project failed, skip to step 3.")
                arcpy.AddWarning("2. If you want to start over, use Maintenance -> Manage Project to remove the project from the list then try step 3.")
                arcpy.AddWarning("3. Wait a few minutes then try running the tool again. You can use ArcGIS Pro Geoprocessing History to rerun with the same settings.")
                arcpy.AddWarning("4. Shift the latitude and longitude by a small amount, then rerun the tool.")
                arcpy.AddWarning("5. Increase or decrease the download extent (radius).")

            for file in [waterxml, poixml, waysxml]:
                if file is not None:
                    file_mb = file.stat().st_size / oneMB
                    if file_mb < 1:
                        if "water" in file.name:
                            arcpy.AddWarning(f"The {file} has a file size < 1MB. If you are downloading for a large area with many water features, it is possible the OSM data did not download correctly. Review the water features feature class in the project geodatabase. Use Maintenance -> Redownload OSM Data as needed.")
                        if "ways" in file.name:
                            arcpy.AddWarning(f"The {file} has a file size < 1MB. If you are downloading for a large area with many roads, it is possible the OSM data did not download correctly. Run step 1B and confirm the network downloaded correctly, then use Maintenance -> Redownload OSM Data as needed.")
                        if "poi" in file.name:
                            arcpy.AddWarning(f"The {file} has a file size < 1MB. If you are downloading for a large area with many possible Points of Interest, it is possible the OSM data did not download correctly. Run step 1C and confirm the network downloaded correctly, then use Maintenance -> Redownload OSM Data as needed.")
            if waterxml is not None:
                messages = custMessenger(custTypes.ARCPYMESSAGE)
                pwater = data_osm_processor.process_OSM_water(projectFolder, waterxml, fgdb, project_polygon, messages)
                pwater.separate_osm_data()


            #pcm = POICategoryManager(project["path"], fgdb)

            maintenance.package_project.add_project(project, PROJECT_FILE)

        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())

        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return

class osm_ways_data:
    """
    Tool to prepare OpenStreetMap (OSM) ways data for network analysis.

    This tool processes 'ways' data from OSM, either:
    - By parsing fresh OSM XML files, or
    - By loading existing pre-processed '.data' files.

    It generates spatial feature classes for network edges ("ways") and junctions required
    for network routing and analysis.

    Parameters:
        out_directory (DEFolder): Folder with existing base dataset, containing the OSM files.
        use_existing (GPBoolean): If True, re-use previously processed data; else parse OSM XML files.
        license_info (GPString, Optional): OpenStreetMap data license info to display.

    Side Effects:
        - May overwrite network feature classes in the geodatabase.
        - Writes log messages within ArcGIS interface.

    Warnings:
        - If 'use_existing' is True but preprocessed data files are missing,
          the tool will error and halt.

    Example Usage:
        On first run: uncheck 'use_existing' to parse XML.
        On subsequent runs: check 'use_existing' to speed processing.

    Raises:
        FileNotFoundError: When required existing processed files are missing.
    """
    def __init__(self):

        """
        Initialize tool label, description, and category for ArcGIS toolbox.
        """
        self.label = "1B. Prepare Network Data from OSM"
        self.description = ""
        self.category = "1 - Create Base Dataset"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)


        license_info = arcpy.Parameter(
            displayName="Use of OpenStreetMap Data",
            name="license_info",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        license_info.value = OSM_LICENSE
        params.append(license_info)

        return params


    def execute(self, parameters, messages):
        import data_osm_processor
        from messenger import custMessenger
        from messenger import custTypes
        from static_tools import helper_functions
        """The source code of the tool."""

        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            messages = custMessenger(custTypes.ARCPYMESSAGE)
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
                
            ways = outputPath / f"{projName}_ways.osm"
            pway = data_osm_processor.process_OSM_ways(outputPath, ways, fgdb, messages)
            arcpy.AddMessage("Processing Ways data")
            arcpy.AddMessage("Processing OSM XML data")
            pway.separate_osm_data()
            arcpy.AddMessage("Creating osm_ways and osm_junctions feature classes...")
            pway.build_data()

        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return
    def postExecute(self):
        """This method takes place after outputs are processed and
        added to the display."""

class osm_poi_data:
    """
    Tool to prepare OpenStreetMap (OSM) Points of Interest (POI) data for accessibility analysis.

    This tool processes OSM POIs from:
    - Freshly downloaded OSM XML POI files, or
    - Existing preprocessed data files in the project geodatabase.

    It creates feature classes containing POIs used as destination points in travel accessibility models.

    Parameters:
        out_directory (DEFolder): Folder path containing the base dataset.
        use_existing (GPBoolean): If True, uses existing processed POI data, skipping initial parsing.
        license_info (GPString, Optional): OpenStreetMap license info displayed as a warning or note.

    Effects:
        - Writes or updates the "osm_pois" feature class in project geodatabase.
        - Generates ArcGIS geoprocessing log messages.

    Notes:
        - For large POI datasets, initial parsing may take significant time.
        - Users should verify existence of expected files when 'use_existing' is True.

    Raises:
        FileNotFoundError: If existing processed data files do not exist but 'use_existing' is True.
    """
    def __init__(self):
        """
        Initialize tool label, description, and category for ArcGIS.
        """

        self.label = "1C. Prepare POI Data from OSM"
        self.description = ""
        self.category = "1 - Create Base Dataset"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        


    def getParameterInfo(self):
        import managers
        import textwrap
        reload(managers)
        """Define the tool parameters."""
        params = []
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        poi_d_categories = arcpy.Parameter(
            displayName="Default POI Categories (Auto-Generated)",
            name="poi_d_categories",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        poi_d_categories.value = "\n".join(textwrap.wrap("; ".join(managers.POICategoryManager.get_default_categories())))
        params.append(poi_d_categories)
        
        poi_categories = arcpy.Parameter(
            displayName="Custom POI Categories to Add",
            name="poi_categories",
            datatype="GPString",       # Set data type to String
            parameterType="Optional",
            direction="Input",
            multiValue=True            # Enable multivalue input
        )
        params.append(poi_categories)

        license_info = arcpy.Parameter(
            displayName="Use of OpenStreetMap Data",
            name="license_info",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        license_info.value = OSM_LICENSE
        params.append(license_info)

        return params

    def execute(self, parameters, messages):
        import data_osm_processor
        from static_tools import helper_functions
        from messenger import custMessenger
        from messenger import custTypes
        import managers

        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            new_categories = parameters[2].values
            if type(new_categories) == str:
                new_categories = new_categories.split(";")

            m = managers.POICategoryManager(outputPath, fgdb)
            if new_categories is not None:
                for x in new_categories:
                    m.add_category_and_tags(x)

            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            
            pois = outputPath / f"{projName}_poi.osm"
            messages = custMessenger(custTypes.ARCPYMESSAGE)
            ppois = data_osm_processor.process_OSM_pois(outputPath, pois, fgdb, messages)
            arcpy.AddMessage("Processing Points of interest data")
            arcpy.AddMessage("Processing OSM XML data")
            ppois.separate_osm_data()
            arcpy.AddMessage("Creating POI feature class...")
            ppois.build_data()
            utm_sr = ppois.utmsr
            arcpy.AddMessage("Creating template custom POIs")
            template_poi_fc = helper_functions.drop_add_featureclass(fgdb,
                                                                    self.schema_info["fc_name_custom_pois_nodes"], 
                                                                    "POINT", 
                                                                    utm_sr)
            ppois.pcm.add_categories_as_fields(template_poi_fc)
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        #finally:
            
        return

    def postExecute(self):
        """This method takes place after outputs are processed and
        added to the display."""


        return
class custom_poi_data:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "1D. Import Custom POI Data (Optional)"
        self.description = ""
        self.category = "1 - Create Base Dataset"
        self.file_path = Path(__file__).parents[0]
        self.settings_info = None
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        feat_layer = arcpy.Parameter(
            displayName="Import Dataset",
            name="feat_layer",
            datatype="GPFeatureLayer",
            parameterType="Required",
            direction="Input")
        feat_layer.filter.list = ['esriGeometryPoint']
        params.append(feat_layer)

        replace_existing = arcpy.Parameter(
            displayName="Replace existing custom POI data",
            name="replace_existing",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input")
        replace_existing.value = True
        params.append(replace_existing)


        return params



    def execute(self, parameters, messages):
        import data_osm_processor
        from static_tools import helper_functions
        from static_tools import random_id
        import managers
        
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            importData = parameters[1].value
            replace_existing = parameters[2].value
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            pcm = managers.POICategoryManager(outputPath, fgdb)
            existing_pois = fgdb / self.schema_info["fc_name_project_pois_nodes"]
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            
            ppois = data_osm_processor.process_OSM_pois(outputPath, outputPath, fgdb)
            if arcpy.Exists(str(existing_pois)) is False:
                arcpy.AddMessage("Project Points of Interest Layer doesn't exist, building")
                ppois.build_fc()
                pcm.add_categories_as_fields(ppois.fc_pois)

            if replace_existing is True:
                arcpy.AddMessage("Replacing existing custom POI data")
                with arcpy.da.UpdateCursor(str(existing_pois), [self.schema_info["field_name_poi_original"]]) as uc:
                    for row in uc:
                        if row[0].startswith("POI"):
                            uc.deleteRow()
                        else:
                            pass

            desc = arcpy.Describe(importData)
            input_sr = desc.SpatialReference
            utm_sr = ppois.utmsr
            if input_sr.factoryCode != utm_sr.factoryCode:
                arcpy.AddMessage("Input layer does not use the same projection. The input POI will be projected to UTM.")

            points = []
            categories_to_fields = pcm.get_category_fields()
            target_fields = [v for v in categories_to_fields.values()]

            search_fields = ["SHAPE@"] + target_fields
            with arcpy.da.SearchCursor(importData, search_fields) as sc:
                for row in sc:
                    geom = row[0]
                    attrs = list(row[1:])
                    if input_sr.factoryCode != utm_sr.factoryCode:
                        geom = geom.projectAs(utm_sr)
                    else:
                        points.append((geom, attrs))

            arcpy.AddMessage("Adding POIS...")
            arcpy.SetProgressor("step", "Inserting POI into feature class...", 0, len(points), 1)
            
            new_ids = []
            insert_fields = ["SHAPE@"] + target_fields + [self.schema_info["field_name_poi_original"], self.schema_info["field_name_poi_finalid"]]
            with arcpy.da.InsertCursor(str(existing_pois),insert_fields) as ic:
                for geom, attrs in points:
                    arcpy.SetProgressorPosition()
                    safe_attrs = [0 if v is None else v for v in attrs]
                    new_id = random_id.create_random_id("POI", new_ids)
                    row_to_insert = [geom] + safe_attrs + [new_id, new_id]
                    ic.insertRow(row_to_insert)
                    new_ids.append(new_id)
            arcpy.ResetProgressor()


        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return
    

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return


class generate_scenario_networks:
    """
    Create a new project scenario geodatabase and download census blocks for the area.

    This tool prepares a working scenario by:
    - Creating a scenario geodatabase.
    - Downloading census blocks within specified origin radius for analysis.
    - Creating origin centroid points for network operations.
    - Optionally subsetting the network by buffer radius.
    - Setting scenario modes like pedestrian, bicycle, vehicle, or others.

    Parameters:
        out_directory (DEFolder): Base dataset folder linking to project data.
        name_for_fc (GPString): Scenario name prefix (no spaces).
        overwrite (GPBoolean, Optional): Flag to overwrite existing scenario.
        slat (GPString): Latitude of scenario center.
        wlong (GPString): Longitude of scenario center.
        origExtent (GPDouble): Radius for origin census block selection (miles).
        buffersubset (GPBoolean): Flag to subset network by radius.
        buffersubsetmi (GPDouble, Optional): Buffer radius in miles for subsetting.
        scenarioModes (GPString, multiValue): List of transportation modes included.

    Effects:
        - Writes scenario geodatabase and related feature classes.
        - Downloads demographic data from census servers.
        - Generates ArcGIS messages and warnings on version mismatches.

    Usage:
        Designed to be run after initial dataset creation to create analysis-ready scenario snapshots.

    Notes:
        Users should verify scenario to be overwritten when 'overwrite' is True.
    """

    def __init__(self):
        """Initialize tool label, description, category and prepare variables."""

        self.label = "2A. Create Project Scenario Dataset"
        self.description = ""
        self.ProjFolder = ""
        self.category = "2 - Create Project Scenarios and Edit Network"
        self.schema_info = load_schema()
        self.settings_info = load_json_settings()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        self.loaded_defaults = False
        self.scenarios = []

    def getParameterInfo(self):
        """Define the tool parameters."""

        self.proj = arcpy.mp.ArcGISProject("CURRENT")
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        nameforfc = arcpy.Parameter(
            displayName="Prefix",
            name="name_for_fc",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        nameforfc.value="Scenario"
        params.append(nameforfc)

        overwrite = arcpy.Parameter(
            displayName="This is the same name as an existing scenario. Overwrite it?",
            name="overwrite",
            datatype="GPBoolean",
            parameterType="Optional",
            direction="Input")
        overwrite.value = False
        overwrite.enabled = False
        params.append(overwrite)

        slat = arcpy.Parameter(
            displayName="Scenario Center Latitude",
            name="slat",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(slat)

        wlong = arcpy.Parameter(
            displayName="Scenario Center Longitude",
            name="wlong",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(wlong)

        buffersubsetmi = arcpy.Parameter(
            displayName="Scenario Radius (Miles from Scenario Center)",
            name="buffersubsetmi",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        buffersubsetmi.value = 10
        buffersubsetmi.enabled = True
        params.append(buffersubsetmi)

        scenarioModes = arcpy.Parameter(
            displayName="Scenario Modes",
            name="scenarioModes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        scenarioModes.filter.list = list(self.settings_info["mode_name_matching"].keys())
        scenarioModes.values = list(self.settings_info["mode_name_matching"].keys())
        params.append(scenarioModes)

        scenarioPOI = arcpy.Parameter(
            displayName="Keep Selected POI Categories",
            name="scenarioPOI",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        scenarioPOI.filter.list = ["Select a project to see the categories."]
        scenarioPOI.values = ["Select a project to see the categories."]
        params.append(scenarioPOI)
        return params

    def check_coverage_area(self, parameters):
        # Coverage Area Check: Is the scenario fully contained in the project extent?
        from static_tools import helper_functions

        proj_name_param = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name_param]["path"])
        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        scenario_name = parameters[1].valueAsText.replace(" ", "_")
        scenario_lat = float(parameters[3].value)
        scenario_lon = float(parameters[4].value)
        buffer_miles = parameters[5].value
        sr = helper_functions.get_wgs84_sr()

        scenario_centroid = arcpy.PointGeometry(arcpy.Point(scenario_lon, scenario_lat), sr)
        # the Buffer tool wants to output a feature class, so we pass it a list instead to trick it 
        # into giving us access to the geometry field without writing to a feature class
        scenario_centroid_buffered = arcpy.analysis.Buffer([scenario_centroid], arcpy.Geometry(), f"{buffer_miles} Miles", method="GEODESIC")
        scenario_polygon = scenario_centroid_buffered[0]
        
        scenario_coverage_area_fc = helper_functions.drop_add_featureclass(Path("memory"), self.schema_info["fc_name_scenario_coverage_area"], "POLYGON", sr)
        helper_functions.drop_add_field(str(scenario_coverage_area_fc), self.schema_info["field_name_scenario_name"], "TEXT",field_alias="Scenario Name")
        helper_functions.drop_add_field(str(scenario_coverage_area_fc), self.schema_info["field_name_scenario_buffer"], "DOUBLE",field_alias="Scenario Radius (Miles)")
        with arcpy.da.InsertCursor(str(scenario_coverage_area_fc), ["SHAPE@", self.schema_info["field_name_scenario_name"], self.schema_info["field_name_scenario_buffer"]]) as ic:
            ic.insertRow([scenario_polygon, scenario_name, buffer_miles])

        project_polygon = [row[0] for row in arcpy.da.SearchCursor(f"{fgdb}/{self.schema_info['fc_name_project_coverage_area']}", ["SHAPE@"])][0]
        scenario_polygon = [row[0] for row in arcpy.da.SearchCursor(str(scenario_coverage_area_fc), ["SHAPE@"])][0]
        intersection_geom = project_polygon.intersect(scenario_polygon, 4)
        intersection_area = intersection_geom.getArea("GEODESIC", "SQUAREMILES")
        scenario_area = scenario_polygon.getArea("GEODESIC", "SQUAREMILES")
        arcpy.AddMessage(f"Scenario area: {scenario_area} sq mi, Intersection area: {intersection_area} sq mi, Ratio: {intersection_area / scenario_area}")
        # Allow for a 1% discrepancy
        if scenario_area > 0:
            if (intersection_area / scenario_area) < 0.99:
                return False, str(scenario_coverage_area_fc)

        return True, str(scenario_coverage_area_fc)

    def updateParameters(self, parameters):
        """
        Update the tool parameters based on user input.

        Args:
            parameters (list): values for each parameter defined in getParameterInfo()

        Returns:
            None
        """
        from managers import POICategoryManager
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            # scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            pcm = POICategoryManager(outputPath, fgdb)
            if self.loaded_defaults is False:
                self.loaded_defaults = True

            # # ensure arcpy gets a string path
            # if arcpy.Exists(str(scenario_table)):
            #     self.scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                
                # if parameters[1].valueAsText in self.scenarios:
                #     idx = 1
                #     while True:
                #         newName = f"Scenario_{idx}"
                #         if newName not in self.scenarios:
                #             parameters[1].value = newName
                #             break
                #         idx += 1

            parameters[3].value = self.projects[proj_name]["latitude"]
            parameters[4].value = self.projects[proj_name]["longitude"]
            parameters[5].value = self.projects[proj_name]["radius"]
            parameters[5].filter.type = "Range"
            parameters[5].filter.list = [0, self.projects[proj_name]["radius"]]
            parameters[7].filter.list = pcm.get_categories()
            parameters[7].values = pcm.get_categories()

            #if parameters[1].valueAsText in self.scenarios:
                
            #    parameters[1].setErrorMessage("This scenario name already exists.")
        return

    def updateMessages(self, parameters):
        """
        Modify the messages created by internal validation for each tool
        parameter.

        Args:
            parameters (list): values for each parameter defined in getParameterInfo()
        """

        if parameters[0].value and parameters[5].value:
            if parameters[5].value > self.projects[parameters[0].valueAsText]["radius"]:
                parameters[5].setErrorMessage(f"Scenario radius is larger than the project radius of {self.projects[parameters[0].valueAsText]['radius']} miles.")

        if parameters[1].altered:
            if parameters[0].value:
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                fgdb = outputPath / f"{projName}_data.gdb"
                scenario_table = fgdb / self.schema_info["fc_scenario_table"]
                # ensure arcpy gets a string path
                if arcpy.Exists(str(scenario_table)):
                    self.scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]

                if parameters[1].valueAsText in self.scenarios:
                    parameters[1].setErrorMessage("This scenario name already exists. Either rename this Scenario or use the Remove Scenario tool to delete the existing Scenario of the same name.")
        
        if parameters[0].value:
            coverage_check_results = self.check_coverage_area(parameters)
            if coverage_check_results[0] is False:
                coverage_area_message = "The Scenario coverage area is not entirely contained within the Project coverage area. Analysis results may be incomplete if this is not addressed. To correct this issue, choose a Scenario center latitude and longitude that is closer to the center of your Project coverage area."
                parameters[3].setWarningMessage(coverage_area_message)
                parameters[4].setWarningMessage(coverage_area_message)
                
        return
    
    def execute(self, parameters, messages):
        """The source code of the tool."""

        import data_scenario_processor
        from static_tools import helper_functions
        from messenger import custMessenger
        from messenger import custTypes
        import data_downloader
        reload(data_scenario_processor)
        
        try:
            proj_name_param = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name_param]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_name = parameters[1].valueAsText.replace(" ", "_")
            scenario_lat = float(parameters[3].value)
            scenario_lon = float(parameters[4].value)
            buffer_miles = parameters[5].value
            modes = parameters[6].values
            categories = parameters[7].values
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                self.scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
            sr = helper_functions.get_wgs84_sr()

            if scenario_name in self.scenarios:
                arcpy.AddWarning(f"Existing scenario names: {','.join(self.scenarios)}")
                arcpy.AddError(f"The scenario name {scenario_name} already exists, please use a distinct name.")
                return

            arcpy.AddMessage(modes)
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            
            # if create_buffer is False:
            #     buffer_miles = None

            scenario = data_scenario_processor.scenario(arcpy.mp.ArcGISProject("CURRENT"),
                                                        outputPath, fgdb, scenario_name,
                                                        buffer_miles, modes,
                                                        scenario_lat, scenario_lon,
                                                        categories)
            scenario.check_category_counts()
            scenario.create_scenario_gdb()
            messages = custMessenger(custTypes.ARCPYMESSAGE)

            coverage_check_results = self.check_coverage_area(parameters)
            if coverage_check_results[0] is False:
                arcpy.AddWarning("The Scenario coverage area is not entirely contained within the Project coverage area. Analysis results may be incomplete if this is not addressed. To correct this issue, re-run this step with a smaller Scenario radius and/or a Scenario center latitude and longitude that is closer to the center of the Project coverage area. Or, re-run from Step 1A to generate a new Project with a larger radius that can fully contain the desired Scenario.")

            arcpy.AddMessage("Creating scenario coverage area feature class.")
            scenario_coverage_area_fc = coverage_check_results[1]
            arcpy.management.CopyFeatures(scenario_coverage_area_fc, str(scenario.scenario_fgdb / self.schema_info["fc_name_scenario_coverage_area"]))

        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return

class manual_edits:
    def __init__(self):

        self.label = "2B. Make Manual Edits to Scenario Network"
        self.description = ""
        self.ProjFolder = None
        self.category = "2 - Create Project Scenarios and Edit Network"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        
    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        
        params.append(directory)
        
        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        p = arcpy.Parameter(
            displayName="After running this tool, make manual edits to the scenario network to reflect your project before proceeding to the next step in the tool.",
            name="p",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        p.value = """
        Once this tool is run, the steps below should be followed 
        to manually adjust the network links to reflect the infrastructure 
        changes you would like to test in your scenario (i.e., new links, 
        removed links, facility changes to existing links, or geometry 
        changes to existing links). Note that only the network links 
        dataset needs to be manually adjusted. The network nodes 
        dataset does not need to be manually adjusted, as these will 
        be taken care of in the next step in the toolbox, which will 
        automatically integrate your changes into the network and 
        generate a final network dataset that is ready for analysis. 
        See the User Guide for more guidance.

        -1: Prepare Network Layer for Editing
        -2: Make Changes to Scenario’s Original Network, If Existing Data 
            is Incomplete or Inaccurate
        -3: Mark Links that are Removed in the Scenario
        -4: Sketch Out New Links for Additional Infrastructure
        -5: Copy Existing Link Geometries and Update Attributes
        -6: Assign Link Attribute Values
        -7: Final Checks"""
        
        params.append(p)

        return params


    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")


    def execute(self, parameters, messages):
        import data_scenario_processor
        from static_tools import helper_functions

        reload(data_scenario_processor)
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenarioName = parameters[1].valueAsText
        inputNetwork = None
        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        scenario_fgdb = outputPath / scenarioName / f"{scenarioName}.gdb"
        schema_info = load_schema()
        settings_info = load_json_settings()
        colors = load_colors()
        proj = arcpy.mp.ArcGISProject("CURRENT")
        data_scenario_processor.scenario.create_working_map(proj, scenario_fgdb, scenarioName, schema_info, colors, settings_info)

        return

    def postExecute(self, parameters):
        return


class integrate_changes_data:
    """
    Integrate an existing scenario into a network, optionally merging external edited layers.

    This tool manages merging scenario edits with the baseline network for analysis.

    Features:
    - Allows choosing between the scenario's OSM data or external input networks.
    - Validates coordinate system matches and projects input data if needed.
    - Creates necessary output feature classes for integrated network.
    - Performs subsetting and network recalculations.
    - Option to split lines longer than a user-defined length.

    Parameters:
        out_directory (GPString): Existing project name, from list of self.projects.keys()
        scenarios (GPString): Scenario name.
        use_OSMData (GPString): Option to use scenario OSM ways or another input layer.
        scenarioname (GPFeatureLayer, Optional): Optional external edited network layer.
        split_lines (GPBoolean): Option to set a maximum line length and split long lines.
        split_length (GPDouble, Optional): Maximum segment length in feet, enabled only if split_lines is True. User input converted to meters.

    Side Effects:
        - Writes new network feature classes.
        - May project and copy input layer data.
        - Writes detailed process message logs, including errors.
        - Temporarily creates intermediate datasets in the geodatabase.

    Errors:
        Raises arcpy errors if copy or projection of input layers fail.
        Aborts executing in certain cases.
        Warns if the project database version differs from the tool version.

    Usage:
        Run after scenario editing to integrate changes for final analysis.

    Example:
        Select scenario "Scenario_1", merge with edits from external feature layer,
        verify projection compatibility.

    """
    def __init__(self):
        """
        Initialize tool label, description, category, and necessary variables.
        """
        self.label = "2C. Integrate Manual Edits into Scenario Network"
        self.description = ""
        self.ProjFolder = None
        self.category = "2 - Create Project Scenarios and Edit Network"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        
    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioname = arcpy.Parameter(
            displayName="Select Edited Scenario Network (Must be a layer in the current Map)",
            name="scenarioname",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input")
        scenarioname.enabled = True
        params.append(scenarioname)
    
        split_lines = arcpy.Parameter(
            displayName="Set maximum line length? This splits network links such that none exceeds the length specified below.",
            name="split_lines",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input")
        split_lines.value = True
        params.append(split_lines)

        split_length = arcpy.Parameter(
            displayName="Maximum Segment Length (Feet)",
            name="split_length",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input",
            enabled=False)
        split_length.value = 500
        params.append(split_length)
        return params

    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")

        if parameters[3].value is True:
                parameters[4].enabled = True
        else:
            parameters[4].enabled = False
        return
    
    def execute(self, parameters, messages):
        import data_scenario_processor
        from static_tools import helper_functions
        reload(data_scenario_processor)
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenarioName = parameters[1].valueAsText
            inputNetwork = None
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            split_lines = parameters[3].value
            split_length = parameters[4].value * 0.3048
            if split_lines is False:
                split_length = None
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")

            layer = parameters[2].value

            descInput = arcpy.Describe(parameters[2].value)
            
            if descInput.dataType == "FeatureLayer":
                if layer.getSelectionSet() is not None:
                    raise Exception("Layer with manual edits has features selected. Clear selection before continuing.")
                if hasattr(descInput, 'isService') and descInput.isService:
                    arcpy.AddMessage("The input network is a feature service layer.")
                else:
                    arcpy.AddMessage("The input network is a feature layer.")
            else:
                arcpy.AddMessage("The input network may not be in the required format.")
                
            integrate_obj = data_scenario_processor.integrate_scenario(outputPath, fgdb, scenarioName)
            arcpy.AddMessage("Creating new feature classes")
            integrate_obj.create_output_fcs()
            inputNetwork1 = parameters[2].valueAsText 
             # use valueAsText if the value is a URL string
            arcpy.AddMessage(f"Input network URL or path: {inputNetwork1}")
            temp_layer_name = "tempLayerForCopy"
            try:
                arcpy.MakeFeatureLayer_management(inputNetwork1, temp_layer_name)
                arcpy.AddMessage("Successfully created feature layer.")
            except Exception as e:
                arcpy.AddError(f"Failed to create feature layer from input: {e}")
                return
            temp_fc = str(fgdb / "temp_inputNetwork_copy")
            if arcpy.Exists(temp_fc):
                arcpy.Delete_management(temp_fc)
            try:
                inputNetwork = arcpy.CopyFeatures_management(temp_layer_name, temp_fc)
                arcpy.AddMessage("Successfully copied features.")
            except Exception as e:
                arcpy.AddError(f"Failed to copy features: {e}")
                return
            desc = arcpy.Describe(inputNetwork)
            if desc.SpatialReference.factoryCode != integrate_obj.utmsr.factoryCode:
                arcpy.AddMessage(f"Mismatched coordinate systems. Projecting to {integrate_obj.utmsr.name}")
                if arcpy.Exists(str(integrate_obj.scenario_fgdb / "temporary_projected_copy")):
                    arcpy.Delete_management(str(integrate_obj.scenario_fgdb / "temporary_projected_copy"))
                inputNetwork = arcpy.Project_management(inputNetwork, str(integrate_obj.scenario_fgdb / "temporary_projected_copy"), integrate_obj.utmsr)
            arcpy.AddMessage("Beginning integration process...")
            integrate_obj.integrate_network(inputNetwork)

            if split_lines is True:
                arcpy.AddMessage("Splitting lines longer than specified length")
                integrate_obj.split_and_reid_links(split_length)
            else:
                integrate_obj.calculate_fft()
            
            integrate_obj.create_map_for_review(arcpy.mp.ArcGISProject("CURRENT"))

            arcpy.AddMessage("Cleaning up temporary files...")
            if arcpy.Exists(temp_fc):
                arcpy.Delete_management(temp_fc)
            if arcpy.Exists(str(integrate_obj.scenario_fgdb / "temporary_projected_copy")):
                arcpy.Delete_management(str(integrate_obj.scenario_fgdb / "temporary_projected_copy"))
            if arcpy.Exists(temp_layer_name):
                arcpy.Delete_management(temp_layer_name)
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return
class centroid_connectors:
    """
    Creates centroid connectors from census block centroids to nearby network nodes.

    This tool performs these key tasks:
    
    - Buffers census block centroids.
    - Identifies nearby network nodes excluding motorway nodes.
    - Builds straight-line connector edges from centroid to nodes.
    - Assigns attributes such as highway type, mode, and pre/post flags.
    - Adds centroid points to junction feature class as origins.

    Parameters:
        out_directory (DEFolder): Folder containing project geodatabase.
        scenarios (GPString): Scenario name.

    Side Effects:
        - Updates network feature classes with new connector edges and points.

    Usage:
        Must be run after network and census data have been prepared and loaded.

    Example:
        Create connectors for pedestrian and bicycle networks within buffer zones.
    """
    def __init__(self):
        """
        Initialize tool label, description, and category.
        """
        self.label = "2D. Identify Origins and Create Connectors"
        self.description = ""
        self.ProjFolder = ""
        self.category = "2 - Create Project Scenarios and Edit Network"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
   
    def getParameterInfo(self):
        """Define the tool parameters."""

        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        origType = arcpy.Parameter(
            displayName="Origin Selection Method",
            name="origType",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        origType.filter.list = ["Census Blocks", "Custom Points", "Custom Polygons"]
        params.append(origType)

        origExtent = arcpy.Parameter(
            displayName="Origin Radius (Miles from Origin Center) for Census Blocks",
            name="origExtent",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        origExtent.value = 0.5
        params.append(origExtent)

        origLat = arcpy.Parameter(
            displayName="Origin Center Latitude (This defaults to the scenario latitude)",
            name="origLat",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        origLat.enabled = False
        params.append(origLat)

        origLon = arcpy.Parameter(
            displayName="Origin Center Longitude (This defaults to the scenario longitude)",
            name="origLon",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        origLon.enabled = False
        params.append(origLon)

        origCustom = arcpy.Parameter(
            displayName="Origin Custom Feature Class",
            name="origCustom",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input")
        params.append(origCustom)

        methods = arcpy.Parameter(
            displayName="Method",
            name="methods",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        methods.filter.list = ["Within a Distance (Recommended for polygons)", "Nearest Neighbor (Recommended for points)"]
        params.append(methods)

        distance = arcpy.Parameter(
            displayName="Within a Distance (ft)",
            name="distance",
            datatype="GPDouble",
            parameterType="Optional",
            direction="Input")
        distance.value = 100
        distance.enabled = False
        params.append(distance)

        return params


    def updateParameters(self, parameters):
        # 1. Project dropdown logic (existing)
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")

        origType = parameters[2].valueAsText
        
        # Did the user just change the Origin dropdown?
        orig_changed = parameters[2].altered and not parameters[2].hasBeenValidated

        # --- 0. UNIVERSAL METHOD LIST ---
        universal_methods = [
            "Within a Distance (Recommended for polygons)", 
            "Nearest Neighbor (Recommended for points)"
        ]
        parameters[7].filter.list = universal_methods

        # --- 1. FORCE DEFAULTS ON ORIGIN CHANGE ---
        if orig_changed:
            if origType == "Custom Points":
                parameters[7].value = universal_methods[1] # Nearest Neighbor
                parameters[8].value = 1000
            else: # Census Blocks or Custom Polygons
                parameters[7].value = universal_methods[0] # Within a Distance
                parameters[8].value = 100

        # --- 2. TOGGLE ORIGIN INPUT UI ---
        if origType == "Census Blocks":
            parameters[3].enabled = True
            parameters[4].enabled = True  # origLat
            parameters[5].enabled = True  # origLon
            parameters[6].enabled = False # origCustom

            if parameters[0].value and parameters[1].value and not (parameters[4].altered and parameters[5].altered):
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                scenario_table = outputPath / f"{projName}_data.gdb" / self.schema_info["fc_scenario_table"]
                
                if arcpy.Exists(str(scenario_table)):
                    with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_lat"], self.schema_info["field_name_scenario_lon"]], f"{self.schema_info['field_name_scenario_name']} = '{parameters[1].valueAsText}'") as cur:
                        for row in cur:
                            if not parameters[4].altered: parameters[4].value = row[0]
                            if not parameters[5].altered: parameters[5].value = row[1]

        elif origType == "Custom Points":
            parameters[3].enabled = False
            parameters[4].enabled = False
            parameters[5].enabled = False
            parameters[6].enabled = True
            parameters[6].filter.list = ["Point"]
            parameters[4].value = None
            parameters[5].value = None

        elif origType == "Custom Polygons":
            parameters[3].enabled = False
            parameters[4].enabled = False
            parameters[5].enabled = False
            parameters[6].enabled = True
            parameters[6].filter.list = ["Polygon"]
            parameters[4].value = None
            parameters[5].value = None

        # --- 3. TOGGLE DISTANCE UI ---
        if parameters[7].valueAsText and "Within a Distance" in parameters[7].valueAsText:
            parameters[8].enabled = True
            # Failsafe if the distance box is completely empty on load
            if parameters[8].value is None:
                parameters[8].value = 1000 if origType == "Custom Points" else 100
        else:
            parameters[8].enabled = False
        
        #If user chooses custom origins (points or polygons), add that corresonding template layer to map if not already open
        if orig_changed and origType in ["Custom Points", "Custom Polygons"]:
            if parameters[0].valueAsText and parameters[1].valueAsText:
                try:
                    proj_name = parameters[0].valueAsText
                    outputPath = Path(self.projects[proj_name]["path"])
                    scenario_name = parameters[1].valueAsText
                    scenario_gdb = outputPath / scenario_name / f"{scenario_name}.gdb"
                    
                    # Get the correct template name from the schema
                    fc_name = self.schema_info["fc_name_custom_origin_points"] if origType == "Custom Points" else self.schema_info["fc_name_custom_origin_polygons"]
                    template_path = scenario_gdb / fc_name
                    
                    if arcpy.Exists(str(template_path)):
                        p = arcpy.mp.ArcGISProject('CURRENT')
                        m = p.activeMap
                        if m:
                            layer_found = None
                            
                            # Check if it is already open in the map
                            for lyr in m.listLayers():
                                if lyr.supports("DATASOURCE") and lyr.dataSource.lower() == str(template_path).lower():
                                    layer_found = lyr
                                    break
                            
                            # Add to map if missing
                            if not layer_found:
                                layer_found = m.addDataFromPath(str(template_path))
                            
                            # Automatically set the UI parameter to the layer
                            parameters[6].value = layer_found
                except Exception:
                    pass # Fail silently so the UI doesn't crash if they don't have an active map open

        return
    
    def check_coverage_area(self, parameters):
        if parameters[2].valueAsText != "Census Blocks":
            return None
            
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        scenario_coverage_fc = outputPath / scenario_name / f"{scenario_name}.gdb" / self.schema_info["fc_name_scenario_coverage_area"]
        
        if arcpy.Exists(str(scenario_coverage_fc)) and parameters[4].value and parameters[5].value and parameters[3].value:
            try:
                orig_radius = float(parameters[3].value)
                orig_lat = float(parameters[4].value)
                orig_lon = float(parameters[5].value)

                scenario_polygon = [row[0] for row in arcpy.da.SearchCursor(str(scenario_coverage_fc), ["SHAPE@"])][0]

                sr = arcpy.SpatialReference(4326)
                origin_centroid = arcpy.PointGeometry(arcpy.Point(orig_lon, orig_lat), sr)

                origin_buffered = arcpy.analysis.Buffer([origin_centroid], arcpy.Geometry(), f"{orig_radius} Miles", method="GEODESIC")
                origin_polygon = origin_buffered[0]

                intersection_geom = scenario_polygon.intersect(origin_polygon, 4)
                intersection_area = intersection_geom.getArea("GEODESIC", "SQUAREMILES")
                origin_area = origin_polygon.getArea("GEODESIC", "SQUAREMILES")
                scenario_area = scenario_polygon.getArea("GEODESIC", "SQUAREMILES")

                is_contained = True
                is_too_much_scenario = False
                is_too_large = False

                if origin_area > 0:
                    if (intersection_area / origin_area) < 0.99:
                        is_contained = False
                if scenario_area > 0:
                    if (origin_area / scenario_area) > 0.5:
                        is_too_much_scenario = True
                if orig_radius > 3:
                    is_too_large = True

                messages = []
                if not is_contained:
                    messages.append("The origin coverage area is not entirely contained within the Scenario coverage area. Analysis results may be incomplete.")
                if is_too_much_scenario:
                    messages.append("The origin area covers more than 50% of the Scenario area, which is unusually large. Origins near the edge of the scenario network may yield incomplete analysis results due to missing data beyond the scenario boundary.")
                if is_too_large:
                    messages.append("The origin radius exceeds 3 miles, which is unusually large. Origins are typically small regions (0.5 to 1.5 miles). A large origin radius increases computation time.")

                return "\n".join(messages)

            except Exception:
                pass # Failsafe for partial UI typing
                
        return None

    def updateMessages(self, parameters):
        if parameters[0].value and parameters[1].value and parameters[3].value:
            messages = self.check_coverage_area(parameters)
            if messages:
                parameters[3].setWarningMessage(messages)
        return

    #For each all census blocks and centroids
    #Buffer each block and intersect nodes in network
    #Remove motorway nodes from this selection (using motorway tag)
    #For this selection, create straight line connector links between centroid and each node
    #Assign new links as highway=centroid_connector
    #Assign mode to centroid connectors using modes identified in the "to" node
    #Assign pre/post flag to centroid connector using pre/post flag in the "to" node
    #Calculate fft walk and add constant penalty (to be substracted later)
    #Add centroids to junction fc and assign as origins


    def execute(self, parameters, messages): 
        #follows the following pattern: initialize network_manager (create_network_table() and get_existing_networks()) -> create_network() -> initialize network_class() -> set_fft() -> build_network() -> get_links() -> G.nx.Digraph() -> G.add_edges_from()
        import data_network
        import data_origins_processor
        import data_downloader
        from messenger import custMessenger
        from messenger import custTypes
        from static_tools import helper_functions
        reload(data_origins_processor)
        
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_name = parameters[1].valueAsText
            
            origType = parameters[2].valueAsText
            radius_origin = float(parameters[3].value) if parameters[3].value else 0

            orig_lat = float(parameters[4].value) if parameters[4].value else None
            orig_lon = float(parameters[5].value) if parameters[5].value else None

            custom_origin_data = parameters[6].value
            method = parameters[7].valueAsText
            distance = float(parameters[8].value) if parameters[8].value else 0

            messages = self.check_coverage_area(parameters)
            if messages:
                arcpy.AddWarning(messages)

            scenario_mode = [row[1] for row in arcpy.da.SearchCursor(str(fgdb / self.schema_info["fc_scenario_table"]), [self.schema_info["field_name_scenario_name"], "modes"]) if row[0] == scenario_name]
            
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                existing_fields = [f.name for f in arcpy.ListFields(str(scenario_table))]
                if "origin_lat" not in existing_fields:
                    helper_functions.drop_add_field(str(scenario_table), self.schema_info["field_name_origin_lat"], "DOUBLE", field_alias="Origin Latitude")
                    helper_functions.drop_add_field(str(scenario_table), self.schema_info["field_name_origin_lon"], "DOUBLE", field_alias="Origin Longitude")
                with arcpy.da.UpdateCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_origin_type"], self.schema_info["field_name_origin_lat"], self.schema_info["field_name_origin_lon"]]) as uc:
                    for row in uc:
                        if row[0] == scenario_name:
                            row[1] = str(origType)
                            row[2] = orig_lat
                            row[3] = orig_lon
                            uc.updateRow(row)
                            break

            cnx = data_origins_processor.connectors(outputPath, scenario_name)
            messages_obj = custMessenger(custTypes.ARCPYMESSAGE)
            
            # 1. Build the Origins
            cnx.build_origins(origType, radius_origin, custom_origin_data, outputPath, messages_obj, orig_lat, orig_lon)

            # 2. Prep Output FCs and Load Centroids to Memory
            cnx.create_output_fcs()
            cnx.get_origin_centroids()

            # 3. Parse Modes
            connector_modes = []
            if len(scenario_mode) > 0:
                for m in scenario_mode[0].split("|"): 
                    if m == "Personal Vehicle":
                        connector_modes.append(data_network.network_manager.MODE_VEHICLE)
                    if m == "Freight Truck":
                        connector_modes.append(data_network.network_manager.MODE_TRUCK)
                    if m == "Bicycle":
                        connector_modes.append(data_network.network_manager.MODE_BICYCLE)
                    if m == "Pedestrian":
                        connector_modes.append(data_network.network_manager.MODE_PEDESTRIAN)
                    if m == "Low Stress Bicycle":
                        connector_modes.append(data_network.network_manager.MODE_PREFERRED_BICYCLE)
                    if m == "Low Stress Pedestrian":
                        connector_modes.append(data_network.network_manager.MODE_PREFERRED_PEDESTRIAN)

            # 4. Generate Connectors
            if method.startswith("Nearest Neighbor"):
                arcpy.AddMessage(f"Using modes: {connector_modes}")
                cnx.create_connectors_nn(connector_modes, True, True, origType)
            elif method.startswith("Within a Distance"):
                cnx.create_connectors_wd(distance, origType)
            else:
                arcpy.AddError("No method selected.")

        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return

class match_to_nodes_data:
    """
    Matches Points of Interest (POIs) to nearest network nodes within a specified distance.

    Performs spatial join operations to associate POIs with network topology for routing.

    Updates scenario metadata with the POI-node matching distance for documentation.

    Parameters:
        out_directory (DEFolder): Project folder path.
        scenarios (GPString): Scenario name.
        POI_distance (GPDouble): Maximum search radius from network nodes to POIs in feet.

    Side Effects:
        - Updates the scenario's project_scenarios table with distance parameter.
        - Creates detail and summary reports of POI associations.

    Notes:
        - Distance must be positive.
        - Requires POI and node datasets to exist in expected geodatabase paths.

    Usage:
        Run after POI data preparation and network creation to assign POIs for accessibility metrics.
    """
    def __init__(self):
        """
        Initialize tool label, category, and basic metadata.
        """
        self.label = "2E. Match POIs to Network Nodes"
        self.category = "2 - Create Project Scenarios and Edit Network"
        self.description = ""
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        POI_distance = arcpy.Parameter(
            displayName="Maximum Search Distance from Network Node to POI (Feet)",
            name="POI_distance",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        POI_distance.value = 300
        params.append(POI_distance)
    
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")

        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
    parameter. This method is called after internal validation."""
        distance = parameters[2].value
        if distance is not None and distance <= 0:
            parameters[2].setErrorMessage("Distance must be a positive number.")
        return


    def execute(self, parameters, messages):
        import data_pois_processor
        from static_tools import helper_functions


        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenarioName = parameters[1].valueAsText
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool...")
            
            POI_distance = float(parameters[2].value) * 0.3048

            mn = data_pois_processor.match_nodes(outputPath, scenarioName, POI_distance)

            if arcpy.Exists(str(mn.poi_data)) is False:
                arcpy.AddError("Project POI feature class does not exist. Please run the Prepare OSM Data for POI tool first.")
                return
                
            if arcpy.Exists(str(mn.node_data)) is False:
                arcpy.AddError("Project network feature classes do not exist. Please run the Integrate Scenario with Existing Network tool first.")
                return

            mn.poimatch()
            
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenario_fields = [f.name for f in arcpy.ListFields(str(scenario_table))]
                if self.schema_info["field_name_scenario_poidist"] not in scenario_fields:
                    helper_functions.drop_add_field(scenario_table, self.schema_info["field_name_scenario_poidist"], "DOUBLE")
                
                with arcpy.da.UpdateCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_scenario_poidist"]]) as uc:
                    for row in uc:
                        if row[0] == scenarioName:
                            row[1] = float(parameters[2].value)
                            uc.updateRow(row)
                            break

            
            mn.summarize_pois()                    
            #mn.create_summary_report()
            


        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""
        return

class build_networks:
    """
    Builds or rebuilds multimodal network datasets necessary for accessibility analysis.

    For each selected transportation mode (vehicle, bicycle, pedestrian, low stress variants),
    builds a corresponding network for routing and travel time calculations.

    Parameters:
        out_directory (DEFolder): Project folder containing geodatabase.
        scenarios (GPString): Scenario name to build networks for.
        rebuild (GPBoolean): If True, rebuild the networks even if they already exist.

    Side Effects:
        - Writes or overwrites network datasets within the project's geodatabase.
        - Logs progress and warnings within ArcGIS environment.

    Usage:
        Run when networks need initial creation or refreshing after edits.

    Raises:
        RuntimeError: If required datasets or scenario tables are missing.
        """
    def __init__(self):
        """
        Initialize tool label, description, category, and internal state.
        """
        self.label = "3A. Convert Networks to Directed Graphs for Analysis"
        self.description = ""
        self.ProjFolder = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""

        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")
        return

    def execute(self, parameters, messages): 
        #follows the following pattern: initialize network_manager (create_network_table() and get_existing_networks()) -> create_network() -> initialize network_class() -> set_fft() -> build_network() -> get_links() -> G.nx.Digraph() -> G.add_edges_from()
        import data_network
        from static_tools import helper_functions
        
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            scenario_mode = [row[1] for row in arcpy.da.SearchCursor(str(fgdb / self.schema_info["fc_scenario_table"]), [self.schema_info["field_name_scenario_name"], "modes"]) if row[0] == scenario_name]
            nm = data_network.network_manager(outputPath, scenario_name) #pass the network manager the project folder, fgdb, and scenario name. Network manager will create the network table and list the existing networks
            for m in scenario_mode[0].split("|"): #for modes and rebuild option selected in paramters, create the network if it doesn't exist or if rebuild is true
                if m == "Personal Vehicle":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_VEHICLE)

                if m == "Freight Truck":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_TRUCK)

                if m == "Bicycle":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_BICYCLE)
                
                if m == "Pedestrian":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_PEDESTRIAN)

                if m == "Low Stress Bicycle":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_PREFERRED_BICYCLE)

                if m == "Low Stress Pedestrian":
                    arcpy.AddMessage(f"Creating network for {m}")
                    nm.create_network(data_network.network_manager.MODE_PREFERRED_PEDESTRIAN)
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return
    #

class accessibility_distances:
    """
    Calculates the network-based distances and free-flow travel times (fft) between origins and destinations.

    Supports multiple modes with different scope limits.

    Parameters:
        out_directory (DEFolder): Project directory path.
        scenarios (GPString): Scenario name.
        mi_vehicle (GPDouble): Maximum vehicle analysis scope in miles.
        mi_ped (GPDouble): Maximum pedestrian analysis scope in miles.
        mi_bike (GPDouble): Maximum bicycle analysis scope in miles.

    Side Effects:
        - Updates network datasets with calculated FFT.
        - Logs detailed warnings for scope exceedances or mismatched versions.

    Usage:
        Run after network buildup; results used as inputs to accessibility metric calculations.

    Raises:
        RuntimeError: For unsupported or missing scenario data.

    """
    def __init__(self):
        """
        Initialize tool label, description, category attributes.
        """
        self.label = "3B. Calculate Distances Between Origins and Destinations"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        mi_vehicle_truck = arcpy.Parameter(
            displayName="Scope of vehicle or truck analysis (miles)",
            name="mi_vehicle or truck",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        params.append(mi_vehicle_truck)

        mi_ped = arcpy.Parameter(
            displayName="Scope of pedestrian analysis (miles)",
            name="mi_ped",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        params.append(mi_ped)

        mi_bike = arcpy.Parameter(
            displayName="Scope of bicycle analysis (miles)",
            name="mi_bike",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        params.append(mi_bike)        

    
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")

        if parameters[1].altered and not parameters[1].hasBeenValidated:
            if parameters[0].valueAsText: # Ensure project is selected
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                fgdb = outputPath / f"{projName}_data.gdb"
                scenario_table = fgdb / self.schema_info["fc_scenario_table"]
                
                if arcpy.Exists(str(scenario_table)) and parameters[1].valueAsText:
                    try:
                        # Grab the radius for this specific scenario
                        where_clause = f"{self.schema_info['field_name_scenario_name']} = '{parameters[1].valueAsText}'"
                        scenario_radius = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_buffer"]], where_clause)][0]
                        
                        parameters[2].filter.type = "Range"
                        parameters[2].filter.list = [0.001, scenario_radius]
                        parameters[2].value = min(25, scenario_radius)
                        
                        parameters[3].filter.type = "Range"
                        parameters[3].filter.list = [0.001, scenario_radius]
                        parameters[3].value = min(3, scenario_radius)
                        
                        parameters[4].filter.type = "Range"
                        parameters[4].filter.list = [0.001, scenario_radius]
                        parameters[4].value = min(10, scenario_radius)
                    except IndexError:
                        pass # Scenario might not be fully written to table yet

        return


    def updateMessages(self, parameters):
        """
        Modify the messages created by internal validation for each tool
        parameter.

        Args:
            parameters (list): values for each parameter defined in getParameterInfo()
        """
        if parameters[0].value:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
        
            if parameters[1].value:
                scenario_radius = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_buffer"]], f"{self.schema_info['field_name_scenario_name']} = '{parameters[1].valueAsText}'")][0]

                if parameters[2].value:
                        if parameters[2].value > scenario_radius:
                            parameters[2].setErrorMessage(f"This vehicle or truck analysis scope is larger than the scenario radius of {scenario_radius} miles.")

                if parameters[3].value:
                    if parameters[3].value > scenario_radius:
                          parameters[3].setErrorMessage(f"This pedestrian analysis scope is larger than the scenario radius of {scenario_radius} miles.")
                        
                if parameters[4].value:
                        if parameters[4].value > scenario_radius:
                            parameters[4].setErrorMessage(f"This bicycle analysis scope is larger than the scenario radius of {scenario_radius} miles.")
        
        return

    def execute(self, parameters, messages):
        import data_network
        reload(data_network)
        from static_tools import helper_functions
        
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            veh_limit = parameters[2].value
            ped_limit = parameters[3].value
            bike_limit = parameters[4].value
            #modes = parameters[2].values

            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            scenario_mode = [row[1] for row in arcpy.da.SearchCursor(str(fgdb / self.schema_info["fc_scenario_table"]), [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_scenario_modes"]]) if row[0] == scenario_name]
            nm = data_network.network_manager(outputPath, scenario_name) #pass the network manager the project folder, fgdb, and scenario name. Network manager will create the network table and list the existing networks

            #TODO - Get a list of the origin and destination nodes to send to the calculation
            #TODO - save out the results...
            origin_node_osmids = [] 
            destination_node_ids = []
            for m in scenario_mode[0].split("|"):

                if m == "Personal Vehicle":
                    nm.process_distance_calculations(data_network.network_manager.MODE_VEHICLE, veh_limit, "fft")

                if m == "Freight Truck":
                    nm.process_distance_calculations(data_network.network_manager.MODE_TRUCK, veh_limit, "fft")

                if m == "Bicycle":
                    nm.process_distance_calculations(data_network.network_manager.MODE_BICYCLE, bike_limit, "fft")
                
                if m == "Pedestrian":
                    nm.process_distance_calculations(data_network.network_manager.MODE_PEDESTRIAN, ped_limit, "fft")

                if m == "Low Stress Bicycle":
                    nm.process_distance_calculations(data_network.network_manager.MODE_PREFERRED_BICYCLE, bike_limit, "fft")
                
                if m == "Low Stress Pedestrian":
                    nm.process_distance_calculations(data_network.network_manager.MODE_PREFERRED_PEDESTRIAN, ped_limit, "fft")
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return

class travel_shed:
    """
    Creates travel shed polygons representing areas reachable from origins within time thresholds.

    Travel sheds are constructed per travel mode, network type, and origin IDs. Used for accessibility visualization.

    Parameters:
        out_directory (DEFolder): Project dataset folder.
        scenarios (GPString): Scenario name.
        modes (GPString, multiValue): Travel modes considered.
        networkType (GPString, multiValue): Network types, e.g., prenetwork, postnetwork.
        threshold (GPLong, multiValue): Time thresholds in minutes.
        origin_id (GPString, multiValue): Origin node IDs.

    Side Effects:
        - Writes shapefiles or feature classes of travel sheds.
        - Logs detailed processing messages.

    Notes:
        - Validates parameters and warns on missing scenario tables.
        - Uses settings.json categories where applicable.

    Example:
        Create travel sheds for pedestrian mode within 15 and 30-minute thresholds from origin ID '12345'.

    """
    def __init__(self):
        """
        Initialize travel_shed label, description, and load scenario settings.
        """
        self.label = "3C. Calculate Accessibility Measures (Travel Shed Areas)"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.settings_info = None
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


    def getParameterInfo(self):
        """Define the tool parameters."""
        
        params = []
        
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioModes = arcpy.Parameter(
            displayName="Modes",
            name="modes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        scenarioModes.filter.type = "ValueList"
        scenarioModes.value = None
        scenarioModes.enabled = True
        scenarioModes.visible = True
        params.append(scenarioModes)

        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}

        networkType = arcpy.Parameter(
            displayName="Pre/Post Network Type",
            name="networkType",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue = True)
        networkType.filter.list = list(self.settings_info["net_type_name_matching"].keys())
        # networkType.value = "prenetwork"
        params.append(networkType)

        threshold = arcpy.Parameter(
            displayName = "Travel Time Threshold",
            name="threshold",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        threshold.filter.type = "ValueList"
        threshold.filter.list = [5,10,15,30,45,60]
        threshold.value = "15"
        threshold.enabled = True
        params.append(threshold)

        origin_lyr = arcpy.Parameter(
            displayName="Origin Layer (selected features only)",
            name="origin_lyr",
            datatype="GPFeatureLayer",
            parameterType="Optional",
            direction="Input")
        origin_lyr.filter.list = ["Point"]
        params.append(origin_lyr)
        
        validated = arcpy.Parameter(
            displayName = "Origin Layer validated? (Check box after fixing any errors)",
            name="validated",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input"
        )
        params.append(validated)

        return params


    def updateParameters(self, parameters):
        # Safe, explicit parameter mapping
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_modes = pmap.get("modes")

        origin_param = pmap.get("origin_lyr")

        # 1) If the project folder changed, refresh scenarios (existing logic)
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = p_out.valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    if p_scenario:
                        p_scenario.setErrorMessage("Create a scenario for your project first.")
                        p_scenario.value = None
                else:
                    if p_scenario:
                        p_scenario.filter.list = scenarios
                        # If no scenario is selected yet, pick the one open on the map or the first one in the list
                        if not (p_scenario.value and str(p_scenario.value).strip()):
                            p = arcpy.mp.ArcGISProject('CURRENT')
                            m = p.activeMap
                            found = False
                            if m:
                                for l in m.listLayers():
                                    if l.supports("DATASOURCE"):
                                        for scenario in scenarios:
                                            if scenario in Path(l.dataSource).parts:
                                                p_scenario.value=scenario
                                                found = True
                                                break
                                    break
                            if not found:
                                p_scenario.value = scenarios[0]
            else:
                if p_scenario:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")

        # 2) If the scenario parameter changed, refresh origin list for the new scenario
        if p_scenario and p_scenario.altered and not p_scenario.hasBeenValidated:
            try:
                # Normalize the selected scenario name
                scenario_name = (p_scenario.valueAsText or str(p_scenario.value) or "").strip()
                # Recompute the connectors_nodes path for the new scenario
                if p_out and p_out.valueAsText:
                    proj_name = p_out.valueAsText
                    outputPath = Path(self.projects[proj_name]["path"])
                    projName = outputPath.name.replace("_project", "")
                    connectors_path = outputPath / scenario_name / f"{scenario_name}.gdb" / self.schema_info["fc_name_origin_nodes"]
                    # add connectors_path to the map here
                    # choose it as origin_lyr parameter
                    p = arcpy.mp.ArcGISProject('CURRENT')
                    m = p.activeMap
                    if arcpy.Exists(str(connectors_path)) and m:
                        # first check if layer is already loaded
                        origins_already_on_map = False
                        for l in m.listLayers():
                            if l.supports("DATASOURCE"):
                                if l.dataSource == str(connectors_path):
                                    l.visible = True
                                    origin_param.value = l
                                    origins_already_on_map = True
                                # get rid of old scenario's origin nodes
                                elif self.schema_info["fc_name_origin_nodes"] == Path(l.dataSource).name:
                                    m.removeLayer(l)
                        if not origins_already_on_map:
                            lyr = m.addDataFromPath(str(connectors_path))
                            origin_param.value = lyr
                    else:
                        arcpy.AddWarning("Origin nodes do not exist in Scenario GDB or no map is loaded")
            except Exception as e:
                arcpy.AddWarning(f"Could not refresh origin list on scenario change: {e}")

        # 3) Existing logic for modes (preserve as-is, but ensure we have a valid p_modes)
        if not ('p_modes' in locals()) or p_modes is None:
            # If not found earlier, try to locate by name in parameters
            for p in parameters:
                if p.name == "modes":
                    p_modes = p
                    break

        # 4) Load settings if needed
        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}

        # 5) Find scenario table helper (unchanged)
        # First checks the expected path: output_path / "{proj_name}_data.gdb" / table.
        # If not found there, it scans:
            # All immediate children of output_path for directories ending with ".gdb".
        # For each candidate .gdb found, it checks if the scenario table exists (using arcpy.Exists). 
            # If found, returns the Path to that table.
        # If nothing is found or an exception occurs, returns None.
        def _find_scenario_table(output_path: Path, proj_name: str, selected_scenario: str):
            cand = output_path / f"{proj_name}_data.gdb" / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(cand)):
                return cand
            try:
                for p in output_path.iterdir():
                    if p.is_dir() and p.suffix.lower() == ".gdb":
                        cand = p / self.schema_info["fc_scenario_table"]
                        if arcpy.Exists(str(cand)):
                            return cand
                    if p.is_dir():
                        for sub in p.iterdir():
                            if sub.is_dir() and sub.suffix.lower() == ".gdb":
                                cand = sub / self.schema_info["fc_scenario_table"]
                                if arcpy.Exists(str(cand)):
                                    return cand
            except Exception:
                pass
            return None

        # 6) Populate modes from the selected scenario (unchanged behavior, but robust)
        try:
            if p_scenario and p_scenario.value is not None and p_out and p_out.valueAsText and p_out.valueAsText.strip():
                selected_scenario = (p_scenario.valueAsText or str(p_scenario.value)).strip()
                proj_name = p_out.valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                scenario_table = _find_scenario_table(outputPath, projName, selected_scenario)
                if scenario_table and arcpy.Exists(str(scenario_table)):
                    modes_field = "modes"
                    modes_list = []
                    # looks for user selected modes from the selected scenario name, 
                    # parses and/or maps mode names as needed
                    with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field]) as cursor:
                        for row in cursor:
                            if row[0] == selected_scenario:
                                raw_modes = row[1] or ""
                                raw_modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                                # don't convert to backend names for display
                                # modes_list = [
                                #     self.settings_info.get("mode_name_matching", {}).get(m, m)
                                #     for m in raw_modes_list
                                # ]
                                modes_list = raw_modes_list
                                break
                    # attempt to find missing p_modes by name from parameters
                    if p_modes is None:
                        for p in parameters:
                            if p.name == "modes":
                                p_modes = p
                                break
                    # stores cleaned mode names in a list              
                    if p_modes:
                        try:
                            p_modes.filter.type = "ValueList"
                            p_modes.filter.list = modes_list
                        except Exception:
                            pass

                        # Preserve user selections if possible
                        # If the user had no previous selections, selects all available modes in ";" separated list
                        # If the preserved selection differs from the current, update the value accordingly
                        try:
                            user_selected = list(p_modes.values) if p_modes.values is not None else []
                        except Exception:
                            user_selected = [v.strip() for v in (p_modes.valueAsText or "").split(";") if v.strip()]

                        if not user_selected:
                            try:
                                p_modes.value = ";".join(modes_list) if modes_list else None
                            except Exception:
                                try:
                                    p_modes.valueAsText = ";".join(modes_list) if modes_list else ""
                                except Exception:
                                    pass
                            self._prev_modes_list = modes_list.copy() if modes_list else []
                        else:
                            preserved = [m for m in user_selected if m in modes_list]
                            try:
                                current_text = p_modes.valueAsText if hasattr(p_modes, "valueAsText") else ""
                            except Exception:
                                current_text = ""
                            current_vals = [v.strip() for v in (current_text or "").split(";") if v.strip()]
                            if preserved and set(preserved) != set(current_vals):
                                try:
                                    p_modes.value = ";".join(preserved)
                                except Exception:
                                    try:
                                        p_modes.valueAsText = ";".join(preserved)
                                    except Exception:
                                        pass
                            self._prev_modes_list = preserved.copy() if preserved else []
            else:
                # If no scenario selected yet, just ensure modes are empty
                if p_modes:
                    try:
                        p_modes.filter.list = []
                        p_modes.value = None
                    except Exception:
                        pass
        except Exception:
            try:
                arcpy.AddWarning("Failed while reading modes from the scenario table.")
            except Exception:
                pass

        # toggle the toggle off if origin layer still has issues
        toggle_param = pmap.get("validated")
        turnToggleOff = False
        if origin_param.value:
            if origin_param.value.getSelectionSet():
                if len(origin_param.value.getSelectionSet()) == 1:
                    pass
                else:
                    turnToggleOff = True
            else:
                turnToggleOff = True

        if turnToggleOff:
            toggle_param.value = False
        return


    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        pmap = {p.name: p for p in parameters}
        origin_param = pmap.get("origin_lyr")
        toggle_param = pmap.get("validated")

        if origin_param.value and origin_param.value.name != self.schema_info["fc_name_origin_nodes"]:
            origin_param.setErrorMessage("You must select the origin nodes layer. Ignore other dropdown options.")
        elif origin_param.value and not origin_param.value.getSelectionSet():
            origin_param.setErrorMessage("You have not selected any origins of interest, or have toggled off the 'Use Selection' switch.\
                                          Select a single origin of interest from the origin nodes layer using the Select tool.")
        elif origin_param.value and len(origin_param.value.getSelectionSet()) != 1:
            origin_param.setErrorMessage("You selected more than one origin node. \
                                         Select a single origin of interest from the origin nodes layer using the Select tool.")
        else:
            origin_param.clearMessage()
        
        if toggle_param.value == False:
            toggle_param.setErrorMessage("Fix any errors in the origin node selection, then toggle this to True to validate before running the tool.")
        ## TODO: replace the following commented out logic with the above if/else statement for more robust error checking
        ## but only if we are able to configure this function to run every time origin_param.value.getSelectionSet changes
        #  
        # if origin_param.value:
        #     origin_layer_getcount = arcpy.management.GetCount(origin_param.value)
        #     if len(origin_param.value.getSelectionSet()) == int(origin_layer_getcount.getOutput(0)):
        #         origin_param.setWarningMessage("It is recommended that you select origins of interest rather than run all origins.")
        #     else:
        #         origin_param.clearMessage()
        return    


    def execute(self, parameters, messages):
        import metrics_accessibility
        reload(metrics_accessibility)
        from static_tools import helper_functions
        
        if parameters[5].value.getSelectionSet():
            if len(parameters[5].value.getSelectionSet()) == 1:
                pass
            else:
                arcpy.AddError("Select only one origin node.")
                raise arcpy.ExecuteError
        else:
            arcpy.AddError("Use the select tool to choose one origin node to run analysis for.")
            raise arcpy.ExecuteError

        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            modes = parameters[2].valueAsText.split(";")
            if not self.settings_info:
                try:
                    self.settings_info = load_json_settings()
                except Exception:
                    self.settings_info = {}
            modes = [self.settings_info["mode_name_matching"].get(lbl.replace("'",""),None) for lbl in modes]
            networktypes = parameters[3].valueAsText.split(";")
            networktypes = [self.settings_info["net_type_name_matching"].get(lbl.replace("'",""),None) for lbl in networktypes]
            thresholds = parameters[4].valueAsText
            # origin_ids_checked = parameters[6].valueAsText
            origin_layer = parameters[5].value

            origin_ids = []
            origin_ids_selected = []
            fieldNameToUse = None
            valuePrefix = ""
            if origin_layer is not None:
                if origin_layer.getSelectionSet() is not None:
                    fields = [f.name for f in arcpy.ListFields(origin_layer)]
                    if self.schema_info["field_name_origin_id"] in fields:
                        fieldNameToUse = self.schema_info["field_name_origin_id"]
                    elif "GEOID" in fields:
                        fieldNameToUse = "GEOID"
                        valuePrefix = "GEOID_"
                    if fieldNameToUse is not None:
                        origin_ids_selected = [f"{valuePrefix}{row[0]}" for row in arcpy.da.SearchCursor(origin_layer, [fieldNameToUse])]
                        origin_ids += origin_ids_selected
                else:
                    arcpy.AddWarning(f"No selection set found for {origin_layer.name}.")
            # origin_ids += origin_ids_checked.split(";")
            origin_ids = list(set(origin_ids))
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")

            thresholds_int = [int(s) for s in thresholds.split(";") if s.strip()]
            arcpy.AddMessage(f"Final origin id list: {origin_ids}")
            metric_args= {
                "modes": modes,
                "networktypes": networktypes,
                "origin_ids": origin_ids,
                "thresholds": thresholds_int
            }       
            mt = metrics_accessibility.metric(projectFolder = outputPath, scenarioName = scenario_name, poi_type_list = [], scenario_modes = modes)
            mt.calc_travel_sheds(metric_args=metric_args)

            # reload travelsheds to map
            # first remove existing on map
            p = arcpy.mp.ArcGISProject('CURRENT')
            m = p.activeMap
            for l in m.listLayers("travel_sheds_*"):
                m.removeLayer(l)
            # now add back to map
            # get candidate layers
            fcs_to_add = {f"travel_sheds_{mode}_{'pre' if network_type == 'prenetwork' else 'post'}": {"mode": mode, "network_type": network_type} for network_type in networktypes for mode in modes}
            for dirpath, dirnames, fcnames in arcpy.da.Walk(str(scenario_fgdb), datatype="FeatureClass"):
                for fc in fcnames:
                    if fc in fcs_to_add.keys():
                        fcs_to_add[fc]["path"] = str(Path(dirpath) / fc)
            
            found_fcs = [fc for fc in fcs_to_add if "path" in fcs_to_add[fc]]
            if not found_fcs:
                arcpy.AddWarning("No origins selected.")
                return

            # load custom color ramp
            style_path = str(self.file_path / "TrACKIT_Legend.stylx")
            
            current_styles = p.styles
            if style_path not in current_styles:
                current_styles.append(style_path)
                p.updateStyles(current_styles)

            #first do all prenetwork layers to ensure that colors are defined
            fcs_pre = [fc for fc in fcs_to_add if fcs_to_add[fc]["network_type"] == "prenetwork"]
            for fc in fcs_pre:
                l = m.addDataFromPath(fcs_to_add[fc]["path"])
                sep = "','"
                l.definitionQuery = f"origin_id in ('{sep.join(origin_ids)}') and threshold in ({','.join([str(i) for i in thresholds_int])})"
                sym = l.symbology
                sym.updateRenderer("UniqueValueRenderer")
                sym.renderer.fields = ["origin_id", "threshold"]
                sym.renderer.colorRamp = p.listColorRamps("TrACKIT Greens")[0]
                for item in sym.renderer.groups[0].items:
                    item.symbol.outlineWidth = 0 
                l.symbology = sym
                l.transparency = 50
                # smaller thresholds on top 
                l_cim = l.getDefinition("V3")
                l_cim.featureSortInfos = [arcpy.cim.CIMFeatureSortInfo(fieldName="threshold", sortDirection=0)]
                l.setDefinition(l_cim)

            fcs_post = [fc for fc in fcs_to_add if fcs_to_add[fc]["network_type"] == "postnetwork"]
            for fc in fcs_post:
                l = m.addDataFromPath(fcs_to_add[fc]["path"])
                sep = "','"
                l.definitionQuery = f"origin_id in ('{sep.join(origin_ids)}') and threshold in ({','.join([str(i) for i in thresholds_int])})"
                sym = l.symbology
                sym.updateRenderer("UniqueValueRenderer")
                sym.renderer.fields = ["origin_id", "threshold"]
                sym.renderer.colorRamp = p.listColorRamps("TrACKIT Greens")[0]
                for item in sym.renderer.groups[0].items:
                    item.symbol.outlineWidth = 1.5
                l.symbology = sym
                # need to apply symb then re-define for colors to be accessible
                sym = l.symbology
                for item in sym.renderer.groups[0].items:
                    item.symbol.outlineColor = item.symbol.color
                    item.symbol.color =  {'RGB' : [0, 0, 0, 0]}
                l.symbology = sym
                l_cim = l.getDefinition("V3")
                l_cim.featureSortInfos = [arcpy.cim.CIMFeatureSortInfo(fieldName="threshold", sortDirection=0)]
                l.setDefinition(l_cim)
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
class travel_shed_density:
    """
    Creates travel shed polygons representing areas reachable from origins within time thresholds.

    Travel sheds are constructed per travel mode, network type, and origin IDs. Used for accessibility visualization.

    Parameters:
        out_directory (DEFolder): Project dataset folder.
        scenarios (GPString): Scenario name.
        modes (GPString, multiValue): Travel modes considered.
        networkType (GPString, multiValue): Network types, e.g., prenetwork, postnetwork.
        threshold (GPLong, multiValue): Time thresholds in minutes.
        origin_id (GPString, multiValue): Origin node IDs.

    Side Effects:
        - Writes shapefiles or feature classes of travel sheds.
        - Logs detailed processing messages.

    Notes:
        - Validates parameters and warns on missing scenario tables.
        - Uses settings.json categories where applicable.
    """

    def __init__(self):
        """
        Initialize travel_shed label, description, and load scenario settings.
        """
        self.label = "X. Calculate Accessibility Measures (Travel Shed Grid)"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.settings_info = None
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        
        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}
        params = []
        
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioModes = arcpy.Parameter(
            displayName="Modes",
            name="modes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        scenarioModes.filter.type = "ValueList"
        scenarioModes.value = None
        scenarioModes.enabled = True
        scenarioModes.visible = True
        params.append(scenarioModes)

        networkType = arcpy.Parameter(
            displayName="Pre/Post Network Type",
            name="networkType",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue = True)
        networkType.filter.list = ["prenetwork", "postnetwork"]
        networkType.value = "prenetwork"
        params.append(networkType)

        threshold = arcpy.Parameter(
            displayName = "Travel Time Threshold",
            name="threshold",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        threshold.filter.type = "ValueList"
        threshold.filter.list = [5,10,15,30,45,60]
        threshold.value = "15"
        threshold.enabled = True
        params.append(threshold)

        origin_id = arcpy.Parameter(
            displayName="Origin ID",
            name="origin_id",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue = True)
        origin_id.filter.list = []
        params.append(origin_id)

        cellSize = arcpy.Parameter(
            displayName="Cell Size (Meters)",
            name="cellSize",
            datatype="GPLong",
            parameterType="Required",
            direction="Input")
        cellSize.value = 30
        params.append(cellSize)
        bandWidth = arcpy.Parameter(
            displayName="Bandwidth (Meters)",
            name="bandWidth",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        bandWidth.value = 300
        params.append(bandWidth)
        return params


    def updateParameters(self, parameters):
        # Safe, explicit parameter mapping
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_modes = pmap.get("modes")

        origin_param = pmap.get("origin_id")

        # 1) If the project folder changed, refresh scenarios (existing logic)
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    if p_scenario:
                        p_scenario.setErrorMessage("Create a scenario for your project first.")
                        p_scenario.value = None
                else:
                    if p_scenario:
                        p_scenario.filter.list = scenarios
                        # If no scenario is selected yet, pick the first by default
                        if not (p_scenario.value and str(p_scenario.value).strip()):
                            p_scenario.value = scenarios[0]
            else:
                if p_scenario:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")

        # 2) If the scenario parameter changed, refresh origin list for the new scenario
        if p_scenario and p_scenario.altered and not p_scenario.hasBeenValidated:
            try:
                # Normalize the selected scenario name
                scenario_name = (p_scenario.valueAsText or str(p_scenario.value) or "").strip()
                # Recompute the connectors_nodes path for the new scenario
                if p_out and p_out.valueAsText:
                    proj_name = parameters[0].valueAsText
                    outputPath = Path(self.projects[proj_name]["path"])
                    projName = outputPath.name.replace("_project", "")
                    connectors_path = outputPath / scenario_name / f"{scenario_name}.gdb" / self.schema_info["fc_name_origin_nodes"]

                    osmid_values = []
                    if arcpy.Exists(str(connectors_path)):
                        with arcpy.da.SearchCursor(str(connectors_path), [self.schema_info["field_name_origin_id"]]) as cur:
                            for row in cur:
                                v = row[0]
                                if v is not None:
                                    osmid_values.append(str(v))
                        osmid_values = list(dict.fromkeys(osmid_values))
                        osmid_values.sort()
                        if origin_param:
                            origin_param.filter.list = osmid_values
                            # Reset selection so user picks a fresh origin for the new scenario
                            origin_param.value = osmid_values[0] if osmid_values else None
                    else:
                        # No connectors_nodes for this scenario; clear origins
                        if origin_param:
                            origin_param.filter.list = []
                            origin_param.value = None
            except Exception as e:
                arcpy.AddWarning(f"Could not refresh origin list on scenario change: {e}")

        # 3) Existing logic for modes (preserve as-is, but ensure we have a valid p_modes)
        if not ('p_modes' in locals()) or p_modes is None:
            # If not found earlier, try to locate by name in parameters
            for p in parameters:
                if p.name == "modes":
                    p_modes = p
                    break

        # 4) Load settings if needed
        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}

        # 5) Find scenario table helper (unchanged)
        def _find_scenario_table(output_path: Path, proj_name: str, selected_scenario: str):
            cand = output_path / f"{proj_name}_data.gdb" / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(cand)):
                return cand
            try:
                for p in output_path.iterdir():
                    if p.is_dir() and p.suffix.lower() == ".gdb":
                        cand = p / self.schema_info["fc_scenario_table"]
                        if arcpy.Exists(str(cand)):
                            return cand
                    if p.is_dir():
                        for sub in p.iterdir():
                            if sub.is_dir() and sub.suffix.lower() == ".gdb":
                                cand = sub / self.schema_info["fc_scenario_table"]
                                if arcpy.Exists(str(cand)):
                                    return cand
            except Exception:
                pass
            return None

        # 6) Populate modes from the selected scenario (unchanged behavior, but robust)
        try:
            if p_scenario and p_scenario.value is not None and p_out and p_out.valueAsText and p_out.valueAsText.strip():
                selected_scenario = (p_scenario.valueAsText or str(p_scenario.value)).strip()
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                scenario_table = _find_scenario_table(outputPath, projName, selected_scenario)
                if scenario_table and arcpy.Exists(str(scenario_table)):
                    modes_field = "modes"
                    modes_list = []
                    with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field]) as cursor:
                        for row in cursor:
                            if row[0] == selected_scenario:
                                raw_modes = row[1] or ""
                                raw_modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                                modes_list = [
                                    self.settings_info.get("mode_name_matching", {}).get(m, m)
                                    for m in raw_modes_list
                                ]
                                break

                    if p_modes is None:
                        for p in parameters:
                            if p.name == "modes":
                                p_modes = p
                                break

                    if p_modes:
                        try:
                            p_modes.filter.type = "ValueList"
                            p_modes.filter.list = modes_list
                        except Exception:
                            pass

                        # Preserve user selections if possible
                        try:
                            user_selected = list(p_modes.values) if p_modes.values is not None else []
                        except Exception:
                            user_selected = [v.strip() for v in (p_modes.valueAsText or "").split(";") if v.strip()]

                        if not user_selected:
                            try:
                                p_modes.value = ";".join(modes_list) if modes_list else None
                            except Exception:
                                try:
                                    p_modes.valueAsText = ";".join(modes_list) if modes_list else ""
                                except Exception:
                                    pass
                            self._prev_modes_list = modes_list.copy() if modes_list else []
                        else:
                            preserved = [m for m in user_selected if m in modes_list]
                            try:
                                current_text = p_modes.valueAsText if hasattr(p_modes, "valueAsText") else ""
                            except Exception:
                                current_text = ""
                            current_vals = [v.strip() for v in (current_text or "").split(";") if v.strip()]
                            if preserved and set(preserved) != set(current_vals):
                                try:
                                    p_modes.value = ";".join(preserved)
                                except Exception:
                                    try:
                                        p_modes.valueAsText = ";".join(preserved)
                                    except Exception:
                                        pass
                            self._prev_modes_list = preserved.copy() if preserved else []
            else:
                # If no scenario selected yet, just ensure modes are empty
                if p_modes:
                    try:
                        p_modes.filter.list = []
                        p_modes.value = None
                    except Exception:
                        pass
        except Exception:
            try:
                arcpy.AddWarning("Failed while reading modes from the scenario table.")
            except Exception:
                pass

        return
        
    

    def execute(self, parameters, messages):
        import metrics_accessibility
        from static_tools import helper_functions
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        modes = parameters[2].valueAsText
        networktypes = parameters[3].valueAsText
        thresholds = parameters[4].valueAsText
        origin_ids = parameters[5].valueAsText
        cellSize = parameters[6].value
        bandwidth = parameters[7].value
        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
        same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
        if same_version is False:
            arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")

        thresholds_int = [int(s) for s in thresholds.split(";") if s.strip()]

        metric_args= {
            "modes": modes.split(";"),
            "networktypes": networktypes.split(";"),
            "origin_ids": origin_ids.split(";"),
            "thresholds": thresholds_int
        }       
        mt = metrics_accessibility.metric(projectFolder = outputPath, scenarioName = scenario_name, poi_type_list = [], scenario_modes = modes)
        densityFGDB = mt.calc_density_maps(metric_args=metric_args, cellSize=cellSize, bandwidth=bandwidth)
        if densityFGDB is not None:
            project = arcpy.mp.ArcGISProject('CURRENT')
            m = project.createMap(helper_functions.sanitize_field_name(self.label), "Map")
            originFC = scenario_fgdb / self.schema_info['fc_name_origin_nodes']
            for origin_id in metric_args["origin_ids"]:
                lyr = arcpy.MakeFeatureLayer_management(str(originFC), f"Origin Location - {origin_id}",  where_clause=f"{self.schema_info['field_name_origin_id']} = '{origin_id}'").getOutput(0)
                m.addLayer(lyr)
                for mode in metric_args["modes"]:
                    for network_type in metric_args["networktypes"]:
                        for threshold in metric_args["thresholds"]:
                            raster_name = f"{origin_id}_{mode}_{network_type}_{threshold}"
                            raster_path = densityFGDB / raster_name
                            lyr = arcpy.MakeRasterLayer_management(str(raster_path), raster_name).getOutput(0)
                            m.addLayer(lyr)


            m.openView()
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
    
class reachable_nodes_summary_report:


    def __init__(self):
        """
        Initialize travel_shed label, description, and load scenario settings.
        """
        self.label = "X. Reachable Nodes Summary Document"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.settings_info = None
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


    def getParameterInfo(self):
        """Define the tool parameters."""
        
        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}
        params = []
        
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioModes = arcpy.Parameter(
            displayName="Modes",
            name="modes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        scenarioModes.filter.type = "ValueList"
        scenarioModes.value = None
        scenarioModes.enabled = True
        scenarioModes.visible = True
        params.append(scenarioModes)

        return params


    def updateParameters(self, parameters):
        # Safe, explicit parameter mapping
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_modes = pmap.get("modes")



        # 1) If the project folder changed, refresh scenarios (existing logic)
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    if p_scenario:
                        p_scenario.setErrorMessage("Create a scenario for your project first.")
                        p_scenario.value = None
                else:
                    if p_scenario:
                        p_scenario.filter.list = scenarios
                        # If no scenario is selected yet, pick the first by default
                        if not (p_scenario.value and str(p_scenario.value).strip()):
                            p_scenario.value = scenarios[0]
            else:
                if p_scenario:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")

        

        # 3) Existing logic for modes (preserve as-is, but ensure we have a valid p_modes)
        if not ('p_modes' in locals()) or p_modes is None:
            # If not found earlier, try to locate by name in parameters
            for p in parameters:
                if p.name == "modes":
                    p_modes = p
                    break


        # 6) Populate modes from the selected scenario (unchanged behavior, but robust)
        try:
            if p_scenario and p_scenario.value is not None and p_out and p_out.valueAsText and p_out.valueAsText.strip():
                selected_scenario = (p_scenario.valueAsText or str(p_scenario.value)).strip()
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                fgdb = outputPath / f"{projName}_data.gdb"
                scenario_table = fgdb / self.schema_info["fc_scenario_table"]
                if scenario_table and arcpy.Exists(str(scenario_table)):
                    modes_field = "modes"
                    modes_list = []
                    with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field]) as cursor:
                        for row in cursor:
                            if row[0] == selected_scenario:
                                raw_modes = row[1] or ""
                                raw_modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                                modes_list = [
                                    self.settings_info.get("mode_name_matching", {}).get(m, m)
                                    for m in raw_modes_list
                                ]
                                break

                    if p_modes is None:
                        for p in parameters:
                            if p.name == "modes":
                                p_modes = p
                                break

                    if p_modes:
                        try:
                            p_modes.filter.type = "ValueList"
                            p_modes.filter.list = modes_list
                        except Exception:
                            pass

                        # Preserve user selections if possible
                        try:
                            user_selected = list(p_modes.values) if p_modes.values is not None else []
                        except Exception:
                            user_selected = [v.strip() for v in (p_modes.valueAsText or "").split(";") if v.strip()]

                        if not user_selected:
                            try:
                                p_modes.value = ";".join(modes_list) if modes_list else None
                            except Exception:
                                try:
                                    p_modes.valueAsText = ";".join(modes_list) if modes_list else ""
                                except Exception:
                                    pass
                            self._prev_modes_list = modes_list.copy() if modes_list else []
                        else:
                            preserved = [m for m in user_selected if m in modes_list]
                            try:
                                current_text = p_modes.valueAsText if hasattr(p_modes, "valueAsText") else ""
                            except Exception:
                                current_text = ""
                            current_vals = [v.strip() for v in (current_text or "").split(";") if v.strip()]
                            if preserved and set(preserved) != set(current_vals):
                                try:
                                    p_modes.value = ";".join(preserved)
                                except Exception:
                                    try:
                                        p_modes.valueAsText = ";".join(preserved)
                                    except Exception:
                                        pass
                            self._prev_modes_list = preserved.copy() if preserved else []
            else:
                # If no scenario selected yet, just ensure modes are empty
                if p_modes:
                    try:
                        p_modes.filter.list = []
                        p_modes.value = None
                    except Exception:
                        pass
        except Exception:
            try:
                arcpy.AddWarning("Failed while reading modes from the scenario table.")
            except Exception:
                pass

        return
        
    
    def execute(self, parameters, messages):
        
        import metrics_accessibility
        from static_tools import helper_functions
        import metrics_nodes_report
        from datetime import datetime
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        modes = parameters[2].valueAsText

        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
        same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
        if same_version is False:
            arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdfPath = outputPath / scenario_name / f"Node_Summary_report_{timestamp}.pdf"
        m = metrics_nodes_report.metric_full(outputPath, scenario_name, None, modes.split(";"))
        m.create_line_plots(pdfPath)
        
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
    
class direction_roses:


    def __init__(self):
        """
        Initialize travel_shed label, description, and load scenario settings.
        """
        self.label = "X. Direction Roses"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.settings_info = None
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


    def getParameterInfo(self):
        """Define the tool parameters."""
        
        if not self.settings_info:
            try:
                self.settings_info = load_json_settings()
            except Exception:
                self.settings_info = {}
        params = []
        
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioModes = arcpy.Parameter(
            displayName="Modes",
            name="modes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        scenarioModes.filter.type = "ValueList"
        scenarioModes.value = None
        scenarioModes.enabled = True
        scenarioModes.visible = True
        params.append(scenarioModes)

        threshold = arcpy.Parameter(
            displayName = "Travel Time Threshold",
            name="threshold",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
            multiValue=False)
        threshold.filter.type = "ValueList"
        threshold.filter.list = [5,10,15,30,45,60]
        threshold.value = 15
        threshold.enabled = True
        params.append(threshold)

        bufferDist = arcpy.Parameter(
            displayName = "Buffer Distance for Wedge Size (feet)",
            name="bufferDist",
            datatype="GPDouble",
            parameterType="Required",
            direction="Input")
        bufferDist.value = 300
        params.append(bufferDist)
        return params


    def updateParameters(self, parameters):
        # Safe, explicit parameter mapping
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_modes = pmap.get("modes")



        # 1) If the project folder changed, refresh scenarios (existing logic)
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    if p_scenario:
                        p_scenario.setErrorMessage("Create a scenario for your project first.")
                        p_scenario.value = None
                else:
                    if p_scenario:
                        p_scenario.filter.list = scenarios
                        # If no scenario is selected yet, pick the first by default
                        if not (p_scenario.value and str(p_scenario.value).strip()):
                            p_scenario.value = scenarios[0]
            else:
                if p_scenario:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")

        

        # 3) Existing logic for modes (preserve as-is, but ensure we have a valid p_modes)
        if not ('p_modes' in locals()) or p_modes is None:
            # If not found earlier, try to locate by name in parameters
            for p in parameters:
                if p.name == "modes":
                    p_modes = p
                    break


        # 6) Populate modes from the selected scenario (unchanged behavior, but robust)
        try:
            if p_scenario and p_scenario.value is not None and p_out and p_out.valueAsText and p_out.valueAsText.strip():
                selected_scenario = (p_scenario.valueAsText or str(p_scenario.value)).strip()
                proj_name = parameters[0].valueAsText
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                fgdb = outputPath / f"{projName}_data.gdb"
                scenario_table = fgdb / self.schema_info["fc_scenario_table"]
                if scenario_table and arcpy.Exists(str(scenario_table)):
                    modes_field = "modes"
                    modes_list = []
                    with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field]) as cursor:
                        for row in cursor:
                            if row[0] == selected_scenario:
                                raw_modes = row[1] or ""
                                raw_modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                                modes_list = [
                                    self.settings_info.get("mode_name_matching", {}).get(m, m)
                                    for m in raw_modes_list
                                ]
                                break

                    if p_modes is None:
                        for p in parameters:
                            if p.name == "modes":
                                p_modes = p
                                break

                    if p_modes:
                        try:
                            p_modes.filter.type = "ValueList"
                            p_modes.filter.list = modes_list
                        except Exception:
                            pass

                        # Preserve user selections if possible
                        try:
                            user_selected = list(p_modes.values) if p_modes.values is not None else []
                        except Exception:
                            user_selected = [v.strip() for v in (p_modes.valueAsText or "").split(";") if v.strip()]

                        if not user_selected:
                            try:
                                p_modes.value = ";".join(modes_list) if modes_list else None
                            except Exception:
                                try:
                                    p_modes.valueAsText = ";".join(modes_list) if modes_list else ""
                                except Exception:
                                    pass
                            self._prev_modes_list = modes_list.copy() if modes_list else []
                        else:
                            preserved = [m for m in user_selected if m in modes_list]
                            try:
                                current_text = p_modes.valueAsText if hasattr(p_modes, "valueAsText") else ""
                            except Exception:
                                current_text = ""
                            current_vals = [v.strip() for v in (current_text or "").split(";") if v.strip()]
                            if preserved and set(preserved) != set(current_vals):
                                try:
                                    p_modes.value = ";".join(preserved)
                                except Exception:
                                    try:
                                        p_modes.valueAsText = ";".join(preserved)
                                    except Exception:
                                        pass
                            self._prev_modes_list = preserved.copy() if preserved else []
            else:
                # If no scenario selected yet, just ensure modes are empty
                if p_modes:
                    try:
                        p_modes.filter.list = []
                        p_modes.value = None
                    except Exception:
                        pass
        except Exception:
            try:
                arcpy.AddWarning("Failed while reading modes from the scenario table.")
            except Exception:
                pass

        return
        
    

    def execute(self, parameters, messages):
        
        import metrics_nodes_report
        from datetime import datetime
        from static_tools import helper_functions
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        modes = parameters[2].valueAsText
        threshold = parameters[3].value
        bufferDistFt = parameters[4].value
        bufferDist = bufferDistFt * 0.3048
        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
        same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
        if same_version is False:
            arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdfPath = outputPath / scenario_name / f"Node_Summary_report_{timestamp}.pdf"
        m = metrics_nodes_report.metric_full(outputPath, scenario_name, None, modes.split(";"))
        directionFGDB = m.create_direction_roses(threshold, bufferDist)
        if directionFGDB is not None:
            project = arcpy.mp.ArcGISProject('CURRENT')
            m = project.createMap(helper_functions.sanitize_field_name(self.label), "Map")
            fc = directionFGDB / "direction_wedges"
            census = scenario_fgdb / self.schema_info["fc_name_census_block_prj"]
            lyr = arcpy.MakeFeatureLayer_management(str(census), "Census Blocks").getOutput(0)
            m.addLayer(lyr)
            if arcpy.Exists(str(fc)) is True:
                for mode in modes.split(";"):
                    lyr = arcpy.MakeFeatureLayer_management(str(fc), mode, where_clause=f"MODE = '{mode}'").getOutput(0)
                    m.addLayer(lyr)
            m.openView()
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
    
class accessibility_measures_cumulative:
    """
    Calculates cumulative accessibility metrics, counting reachable POIs within travel time thresholds.

    Generates accessibility profiles aggregating number of destinations reachable under different
    travel time cutoffs for various modes.

    Parameters:
        out_directory (DEFolder): Project folder path.
        scenarios (GPString, Optional): Scenario to analyze.
        categories (GPString, multiValue): POI categories to compute cumulative accessibility.
        modes (GPString, multiValue): Travel modes considered.
        thresholds_cum (GPLong, multiValue): Travel time thresholds (in minutes).

    Side Effects:
        - Writes output metrics to geodatabase or equivalent storage.
        - Logs progress and warnings into ArcGIS interface.

    Notes:
        - Requires scenario network datasets built in advance.
        - Categories and modes loaded from settings file.

    Example:
        Compute cumulative accessibility for categories "Health Care", "Education" at 15,30,60-minute thresholds.

    """
    def __init__(self):
        """
        Initialize tool label, category, and prepare category list.
        """
        self.label = "3D. Calculate Accessibility Measures (Cumulative)"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.file_path = Path(__file__).parents[0]
        self.settings_info = None
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


    def getParameterInfo(self):
        
        params = []
        # Project folder
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        # Scenario (populated in updateParameters)
        p_scenario = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        p_scenario.filter.list = []
        params.append(p_scenario)

            # assign to self before you reference it anywhere else
        #self._category_list = self._category_list 

        p_categories = arcpy.Parameter(
            displayName="POI Categories",
            name="categories",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        p_categories.filter.type = "ValueList"
        p_categories.filter.list = []
        params.append(p_categories)
            
        p_modes = arcpy.Parameter(
            displayName="Modes",
            name="modes",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        p_modes.filter.type = "ValueList"
        p_modes.value = None
        p_modes.enabled = True
        p_modes.visible = True
        params.append(p_modes)
            
        p_thresholds_cum = arcpy.Parameter(
            displayName="Thresholds (minutes)",
            name="thresholds_cum",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        p_thresholds_cum.filter.type = "ValueList"
        p_thresholds_cum.filter.list = [5,10,15,30,45,60]
        p_thresholds_cum.value = "15"
        p_thresholds_cum.enabled = True
        params.append(p_thresholds_cum)

        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_categories = pmap.get("categories")
        p_modes = pmap.get("modes")

        # 1) Populate scenarios when project folder changed
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = p_out.valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if not scenarios:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")
                else:
                    p_scenario.filter.list = scenarios
                    if not (p_scenario.value and str(p_scenario.value).strip()):
                        p_scenario.value = scenarios[0]
            else:
                p_scenario.setErrorMessage("Create a scenario for your project first.")

        # 2) Update lists when scenario changes
        if p_scenario and p_scenario.altered and not p_scenario.hasBeenValidated:
            if p_modes: p_modes.values = []
            if p_categories: p_categories.values = []
            
            selected_scenario = p_scenario.valueAsText or str(p_scenario.value)
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            
            if arcpy.Exists(str(scenario_table)):
                modes_field = "modes"
                cats_field = self.schema_info["field_name_selected_poi_categories"]
                modes_list = []
                cats_list = []
                
                with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field, cats_field]) as cursor:
                    for row in cursor:
                        if row[0] == selected_scenario:
                            raw_modes = row[1] or ""
                            modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                            raw_cats = row[2] or ""
                            cats_list = [c.strip() for c in raw_cats.split("|") if c.strip()]
                            break
                            
                if p_modes:
                    p_modes.filter.list = modes_list
                    p_modes.values = modes_list # Auto-check the valid ones
                    
                if p_categories:
                    p_categories.filter.list = cats_list
                    p_categories.values = cats_list # Auto-check the valid ones

        return


    def execute(self, parameters, messages):
        import metrics_accessibility
        from static_tools import helper_functions
        sys.settrace(raiseIfCancelled)
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            modes_field = "modes"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            poi_type_list = parameters[2].values
            scenario_modes_labels = parameters[3].values
    
            scenario_modes = [self.settings_info["mode_name_matching"].get(lbl,None) for lbl in scenario_modes_labels]
            scenario_modes = [m for m in scenario_modes if m is not None]
            thresholds_dict = parameters[4].values
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            m = metrics_accessibility.metric(outputPath, scenario_name, poi_type_list, scenario_modes)
            m.calculate_metrics(metric_type=metrics_accessibility.metric.CUMULATIVE_METRIC, metric_args={"thresholds": thresholds_dict})
            sys.settrace(None)
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        finally:
            sys.settrace(None)
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
            added to the display."""


        return    

class accessibility_measures_dual:
    """
    Calculates dual accessibility metrics for a scenario across multiple POI types and modes.

    Dual metrics represent counts of destinations reachable given a threshold count of POIs.

    Parameters:
        out_directory (DEFolder): Project folder location.
        scenarios (GPString, Optional): Name of the scenario; optional if project default used.
        modes_dual (GPString, multiValue): Travel modes to include (e.g., vehicle, bicycle).
        thresholds_dual (GPValueTable): Table specifying POI categories and minimum destination counts.

    Side Effects:
        - Writes accessibility metrics to disk/feature classes.
        - Produces detailed compliance reports and ArcGIS messages.

    Notes:
        - Requires preprocessed network and node data.
        - Thresholds are integral counts representing accessibility criteria.

    Example:
        Calculate dual accessibility with thresholds like "Grocery Stores >= 5" and "Schools >= 3".

    """
    def __init__(self):
        """
        Initialize tool label, category, and load configuration settings.
        """
        self.label = "3E. Calculate Accessibility Measures (Dual)"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self._param_map = {}
        self._category_list = []
        self.settings_info = None
        self.file_path = Path(__file__).parents[0]
        self.settings_info = load_json_settings()
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)


    def getParameterInfo(self):
               
        params = []

        # Project folder
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        # Scenario (populated in updateParameters)
        p_scenario = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        p_scenario.filter.list = []
        params.append(p_scenario)



        # p_categories = arcpy.Parameter(
        #     displayName="POI Categories",
        #     name="categories",
        #     datatype="GPString",
        #     parameterType="Required",
        #     direction="Input",
        #     multiValue=True
        # )
        # p_categories.filter.type = "ValueList"
        # p_categories.filter.list = self._category_list  # your categories list
        
        # params.append(p_categories)
        
        p_modes = arcpy.Parameter(
            displayName="Modes",
            name="modes_dual",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True
        )
        p_modes.filter.type = "ValueList"
        p_modes.value = None
        p_modes.enabled = True
        p_modes.visible = True
        params.append(p_modes)

        p_thresholds_dual = arcpy.Parameter(
            displayName="Thresholds",
            name="thresholds_dual",
            datatype="GPValueTable",
            parameterType="Required",
            direction="Input"
        )
        p_thresholds_dual.columns = [["GPString", "POI Category"], ["GPLong", "Number of destinations"]]
        p_thresholds_dual.enabled = True
        p_thresholds_dual.filters[0].type = "ValueList"
        p_thresholds_dual.filters[1].type = "Range"
        p_thresholds_dual.filters[0].list = self._category_list
        p_thresholds_dual.filters[1].list = [1, 100]

        params.append(p_thresholds_dual)


        return params

    def isLicensed(self):
        return True

    def updateParameters(self, parameters):
        pmap = {p.name: p for p in parameters}
        p_out = pmap.get("out_directory")
        p_scenario = pmap.get("scenarios")
        p_modes = pmap.get("modes_dual")
        p_thresholds_dual = pmap.get("thresholds_dual")

        # 1) Populate scenarios when project folder changed
        if p_out and p_out.altered and not p_out.hasBeenValidated:
            proj_name = p_out.valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if not scenarios:
                    p_scenario.setErrorMessage("Create a scenario for your project first.")
                else:
                    p_scenario.filter.list = scenarios
                    if not (p_scenario.value and str(p_scenario.value).strip()):
                        p_scenario.value = scenarios[0]
            else:
                p_scenario.setErrorMessage("Create a scenario for your project first.")

        # 2) Update lists when scenario changes
        if p_scenario and p_scenario.altered and not p_scenario.hasBeenValidated:
            # Clear old values to prevent red validation errors when switching scenarios
            if p_thresholds_dual: p_thresholds_dual.values = []
            if p_modes: p_modes.values = []
            
            selected_scenario = p_scenario.valueAsText or str(p_scenario.value)
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            
            if arcpy.Exists(str(scenario_table)):
                modes_field = "modes" 
                cats_field = self.schema_info["field_name_selected_poi_categories"]
                modes_list = []
                cats_list = []
                
                with arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"], modes_field, cats_field]) as cursor:
                    for row in cursor:
                        if row[0] == selected_scenario:
                            raw_modes = row[1] or ""
                            modes_list = [m.strip() for m in raw_modes.split("|") if m.strip()]
                            raw_cats = row[2] or ""
                            cats_list = [c.strip() for c in raw_cats.split("|") if c.strip()]
                            break
                            
                if p_modes:
                    p_modes.filter.list = modes_list
                    p_modes.values = modes_list 

                if p_thresholds_dual:
                    # Supply the valid categories to the dropdown list
                    p_thresholds_dual.filters[0].list = cats_list
                    # Note: We intentionally DO NOT set p_thresholds_dual.values here so the grid stays blank!
        
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        pmap = {p.name: p for p in parameters}
        p_thresholds_dual = pmap.get("thresholds_dual")
        if p_thresholds_dual.altered and not p_thresholds_dual.hasBeenValidated:
            duplicates = []
            if p_thresholds_dual.values is not None:
                for x in p_thresholds_dual.values:
                    if x[0] in duplicates:
                        p_thresholds_dual.setErrorMessage("Duplicate mode values are not allowed.")
                    else:
                        duplicates.append(x[0])
        return
    

    def execute(self, parameters, messages):
        import metrics_accessibility
        from static_tools import helper_functions
        
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            modes_field = "modes"
            same_version = helper_functions.tool_project_version_check(fgdb, TOOLBOX_VERSION)
            if same_version is False:
                arcpy.AddWarning("The project database was not created under the same version of the current tool. This may cause unexpected errors. Consider upgrading the project or recreating it.")
            #poi_type_list = parameters[2].values
            scenario_modes_labels = parameters[2].values

            scenario_modes = [self.settings_info["mode_name_matching"].get(lbl, lbl) for lbl in scenario_modes_labels]
            thresholds_dict = {row[0]: row[1] for row in parameters[3].values}
            poi_type_list = list(thresholds_dict.keys())
            m = metrics_accessibility.metric(outputPath, scenario_name, poi_type_list, scenario_modes)
            metric_args = {poi_type: thresholds_dict[poi_type] for poi_type in poi_type_list if poi_type in thresholds_dict}
            m.calculate_metrics(metric_type=metrics_accessibility.metric.DUAL_METRIC, metric_args=metric_args)
            
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        
     
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
    
class report:
    """
    Generates reports and visualization outputs for accessibility analysis metrics.

    Allows selection of metrics, scenario, and target files for generating PDF or GIS-based reports.

    Parameters:
        out_directory (DEFolder): Project directory path.
        scenarios (GPString): Scenario to report on.
        metrics (GPString): Selected metric(s) to include in the report.
        files (GPString, multiValue): Files related to metrics for report inclusion.

    Side Effects:
        - Creates report files and visuals stored within project directory.
        - Outputs progress and error messages in the ArcGIS environment.

    Notes:
        - Metric and file lists updated dynamically based on scenario selection.
        - Integration with ArcGIS Pro visualization tools expected.

    """
    def __init__(self):
        """
        Initialize tool label, description, category for report generation.
        """
        self.label = "3F. Generate Reports and Visuals for Generated Metrics"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        metrics = arcpy.Parameter(
            displayName="Metrics to include in report",
            name="metrics",
            datatype="GPString",
            direction="Input",
            parameterType="Required",
            multiValue=False)
        metrics.filter.type = "ValueList"
        metrics.filter.list = []
        params.append(metrics)

        files = arcpy.Parameter(
            displayName="Files to run metrics on",
            name = "files",
            datatype="GPString",
            direction="Input",
            parameterType="Required",
            multiValue=True)
        files.filter.type = "ValueList"
        files.filter.list = []
        params.append(files)

        weight = arcpy.Parameter(
            displayName="Field to use for report weighting",
            name="weight",
            datatype="GPString",
            direction="Input",
            multiValue=False)
        weight.filter.list = []
        params.append(weight)
        
        maps = arcpy.Parameter(
            displayName = "Generate maps in report?",
            name = "maps",
            datatype = "GPBoolean",
            direction = "Input",
            parameterType="Required",
            multiValue = False)
        maps.value = False
        maps.enabled = True
        params.append(maps)

        mapsKeep = arcpy.Parameter(
            displayName = "Keep maps in this ArcGIS Pro Project?",
            name = "mapsKeep",
            datatype = "GPBoolean",
            direction = "Input",
            parameterType="Optional")
        mapsKeep.value = True
        mapsKeep.enabled = True
        params.append(mapsKeep)   

        return params
    
    def isLicensed(self):
        return True

    def updateParameters(self, parameters):

        import pickle 

        p_out = parameters[0]
        p_scenario = parameters[1]
        p_metrics = parameters[2]
        p_files = parameters[3]
        p_weight = parameters[4]

        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")

        
        if p_out and p_out.valueAsText and p_scenario and (p_scenario.valueAsText or p_scenario.value):
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = (p_scenario.valueAsText or str(p_scenario.value)).strip()
            scenario_folder = outputPath / scenario_name
            candidates = []
            if scenario_folder.exists() and scenario_folder.is_dir():
                for p in scenario_folder.iterdir():
                    if p.is_dir():
                        name = p.name
                        if name.startswith(f"{scenario_name}_dual_") or name.startswith(f"{scenario_name}_cumu_"):
                            candidates.append(str(p.name))
            candidates.sort()
            if p_metrics:
                p_metrics.filter.list = candidates
        
            if p_metrics:
                selected_metric = p_metrics.valueAsText or str(p_metrics.value) or ""
                if selected_metric:
                    outputPath = Path(self.projects[proj_name]["path"])
                    scenario_name = (p_scenario.valueAsText or str(p_scenario.value)).strip()
                    scenario_folder = outputPath / scenario_name / selected_metric
                    files = []
                    for p in scenario_folder.glob("*.metrics"):
                        files.append(str(p.name))
                    files.sort()
                    p_files.filter.list = files

        if p_files and p_files.valueAsText and p_out and p_out.valueAsText and p_metrics and p_metrics.valueAsText and p_scenario and (p_scenario.valueAsText or p_scenario.value):
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = (p_scenario.valueAsText or str(p_scenario.value)).strip()
            scenario_folder = outputPath / scenario_name
            selected_metric = p_metrics.valueAsText or str(p_metrics.value) or ""

            if p_files.values and len(p_files.values) > 0:
                selected_file = str(p_files.values[0])
            else:
                selected_file_raw = p_files.valueAsText or str(p_files.value) or ""
                selected_file = selected_file_raw.split(";")[0].strip("'\" ")

            file_path = outputPath / scenario_name / selected_metric / selected_file
            if file_path.exists() and file_path.is_file():
                try:
                    with open(file_path, 'rb') as file:
                        df = pickle.load(file)
                    if df.empty:
                        p_weight.filter.list = []
                    else:
                        raw_weights = df.select_dtypes(include='number').columns.tolist()
                        exclude_exact = {"objectid", "shape_length", "shape_area", "orig_fid", "travel_time_sec", "nth_destination"}
                        weights = [
                            w for w in raw_weights 
                            if w.lower() not in exclude_exact and not w.lower().startswith("within_")
                            ]
                        p_weight.filter.list = weights
                except Exception:
                    p_weight.filter.list=[]
        return

    def updateMessages(self, parameters):
        import pickle
        p_out = parameters[0]
        p_scenario = parameters[1]
        p_metrics = parameters[2]
        p_files = parameters[3]

        if p_files and p_files.altered and p_files.valueAsText and p_out and p_out.valueAsText and p_metrics and p_metrics.valueAsText and p_scenario and (p_scenario.valueAsText or p_scenario.value):
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = (p_scenario.valueAsText or str(p_scenario.value)).strip()
            selected_metric = p_metrics.valueAsText or str(p_metrics.value) or ""

            if p_files.values and len(p_files.values) > 0:
                selected_file = str(p_files.values[0])
            else:
                selected_file_raw = p_files.valueAsText or str(p_files.value) or ""
                selected_file = selected_file_raw.split(";")[0].strip("'\" ")

            file_path = outputPath / scenario_name / selected_metric / selected_file
            
            if file_path.exists() and file_path.is_file():
                try:
                    with open(file_path, 'rb') as file:
                        df = pickle.load(file)
                    if df.empty:
                        p_files.setWarningMessage(f"The selected file '{selected_file}' contains no data.")
                except EOFError:
                    p_files.setErrorMessage(f"The file '{selected_file}' is empty or corrupted. Please re-run the previous tool.")
                except Exception as e:
                    p_files.setErrorMessage(f"Could not read the metric file: {e}")
                    
        return

    def execute(self, parameters, messages):
        import metrics_report
        import metrics_accessibility
        reload(metrics_report)

        sys.settrace(raiseIfCancelled)
        try:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            scenario_name = parameters[1].valueAsText
            metrics_folder = parameters[2].valueAsText
            metrics = list(parameters[3].values) if parameters[3].values is not None else []
            weight_field = parameters[4].valueAsText
            generate_maps = parameters[5].value
            keep_maps = parameters[6].value
            
            metric_paths = [str(m) for m in metrics]
            arcpy.AddMessage(f"{metric_paths}")

            if "cumu" in metrics_folder.lower():
                metrics_type = metrics_accessibility.metric.CUMULATIVE_METRIC
            else:
                metrics_type = metrics_accessibility.metric.DUAL_METRIC

        

            m = metrics_report.generate_report(projectFolder = outputPath, 
                                                scenarioName = scenario_name, 
                                                metricsFolder = metrics_folder, 
                                                metrics = metric_paths, 
                                                metrics_type = metrics_type,
                                                metrics_weight = weight_field)
            if generate_maps is False:
                m.REPORT_CREATE_POP_MAP = False
                m.REPORT_CREATE_ACCESS_MAPS = False

            if keep_maps is False:
                m.REMOVE_MAP_OBJECTS = True
                
            m.create_report()
            sys.settrace(None)
        except Exception as e:
            arcpy.AddError(str(e))
            arcpy.AddError(traceback.format_exc())
        finally:
            sys.settrace(None)

        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return


class upgrade_project:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Upgrade Project to Current Version"
        self.description = ""
        self.category = "Maintenance"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)
    
        typeofupgrade = arcpy.Parameter(
            displayName="Upgrade Process",
            name="typeofupgrade",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        typeofupgrade.filter.list = ["Upgrade water features","Upgrade for schema change"]
        params.append(typeofupgrade)
        return params

    def updateParameters(self, parameters):

        return

    def execute(self, parameters, messages):
        import data_osm_processor
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        projName = outputPath.name.replace("_project", "")
        fgdb = outputPath / f"{projName}_data.gdb"
        if parameters[1].value == "Upgrade water features":
            upgrade = maintenance.update_water_features(outputPath)
            upgrade.upgrade_database()
        else:
            upgrade = maintenance.update_alpha_to_beta(outputPath)
            upgrade.upgrade_database()
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return


class manage_project:
    def __init__(self):
        """Define the tool (tool name is the name of the class)."""
        self.label = "Manage Projects"
        self.description = ""
        self.category = "Maintenance"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []


        options = arcpy.Parameter(
            displayName="Operation",
            name="options",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        options.filter.list = ["Rename Project", "Remove Project Name", "Remove Project Name and Delete from Disk", "Rename Scenario",
                               "Remove Scenario Name", "Remove Scenario Name and Delete from Disk",
                               "Export Project as Zip Archive", "Import Zip Archive as Project", "Import Folder as Project"]
        params.append(options)

        existing_project = arcpy.Parameter(
            displayName="Existing Project",
            name="existing_project",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=False)
        existing_project.filter.list = list(self.projects.keys())
        existing_project.enabled = False
        params.append(existing_project)
        existing_project_mv = arcpy.Parameter(
            displayName="Existing Project",
            name="existing_project_mv",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)
        existing_project_mv.filter.list = list(self.projects.keys())
        existing_project_mv.enabled = False
        params.append(existing_project_mv)
        scenarios = arcpy.Parameter(
            displayName="Scenarios",
            name="scenarios",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=False)
        scenarios.filter.list = []
        scenarios.enabled = False
        params.append(scenarios)
        scenarios_mv = arcpy.Parameter(
            displayName="Scenarios",
            name="scenarios_mv",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
            multiValue=True)
        scenarios_mv.filter.list = []
        scenarios_mv.enabled = False
        params.append(scenarios_mv)

        newname = arcpy.Parameter(
            displayName="New Name",
            name="newname",
            datatype="GPString",
            parameterType="Optional",
            direction="Input")
        newname.enabled = False
        params.append(newname)

        in_file = arcpy.Parameter(
            displayName="Project Zip File",
            name="in_file",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input")
        in_file.filter.list = ['zip']
        in_file.enabled = False
        params.append(in_file)

        directory = arcpy.Parameter(
            displayName="Import this project Folder",
            name="out_directory",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")
        directory.enabled = False
        params.append(directory)

        directory2 = arcpy.Parameter(
            displayName="Extract Zip to this Folder",
            name="out_directory2",
            datatype="DEFolder",
            parameterType="Optional",
            direction="Input")
        directory2.enabled = False
        params.append(directory2)


        

        

        return params


    def updateParameters(self, parameters):

        if parameters[0].altered and not parameters[0].hasBeenValidated:
            for i in range(1, len(parameters)):
                parameters[i].enabled = False

            if parameters[0].valueAsText == "Rename Project":
                parameters[1].enabled = True
                parameters[5].enabled = True
            elif parameters[0].valueAsText == "Rename Scenario":
                parameters[1].enabled = True
                parameters[3].enabled = True
                parameters[5].enabled = True
            elif parameters[0].valueAsText in ["Remove Project Name", "Remove Project Name and Delete from Disk"]:
                parameters[2].enabled = True
            elif parameters[0].valueAsText in ["Remove Scenario Name", "Remove Scenario Name and Delete from Disk"]:
                parameters[1].enabled = True
                parameters[4].enabled = True
            elif parameters[0].valueAsText == "Export Project as Zip Archive":
                parameters[1].enabled = True
            elif parameters[0].valueAsText == "Import Folder as Project":
                parameters[7].enabled = True
            
            elif parameters[0].valueAsText == "Import Zip Archive as Project":
                parameters[6].enabled = True
                parameters[8].enabled = True
        #if parameters[1].enabled is True and parameters[6].enabled is True:
        if parameters[1].altered and not parameters[1].hasBeenValidated:
            if parameters[2].enabled is True:
                proj_name = parameters[2].values[0]
            else:
                proj_name = parameters[1].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[3].setErrorMessage("Create a scenario for your project first.")
                    parameters[3].value = "Create a scenario for your project first."
                    parameters[4].value = "Create a scenario for your project first."
                else:
                    parameters[3].filter.list = scenarios
                    parameters[3].value = scenarios[0]
                    parameters[4].filter.list = scenarios
                    parameters[4].value = scenarios[0]
        return

    def updateMessages(self, parameters):
        """Modify the messages created by internal validation for each tool
        parameter. This method is called after internal validation."""
        if parameters[8].altered:
            import zipfile
            if parameters[8].valueAsText and parameters[6].valueAsText:
                outFolder = parameters[8].valueAsText
                warnings = 0
                warningMessage = "Potential issues with your output folder location.\n"
                if "-" in outFolder:
                    warningMessage += "The path contains a dash.\n"
                    warnings += 1
                if " " in outFolder:
                    warningMessage += "The path contains a space.\n"
                    warnings += 1
                maxnames = 0
                with zipfile.ZipFile(parameters[6].valueAsText, 'r') as zip_ref:
                    for name in zip_ref.namelist():
                        maxnames = max(maxnames, len(name))
                if len(outFolder)+maxnames > 150:
                    warningMessage += "The path to the output folder is likely too long. This can cause problems when extracting the zip file. Choose a higher level folder.\n"
                    warnings += 1
                if warnings > 0:
                    parameters[8].setWarningMessage(warningMessage)

        return


    def get_proj_info(self, proj_name):
        outputPath = None
        projName = None
        fgdb = None
        if proj_name is not None or proj_name != "":
            try:
                outputPath = Path(self.projects[proj_name]["path"])
                projName = outputPath.name.replace("_project", "")
                fgdb = outputPath / f"{projName}_data.gdb"
            except:
                proj_name = None
        return (outputPath, projName, fgdb)

    def execute(self, parameters, messages):
        reload(maintenance)

        if parameters[0].valueAsText == "Rename Project":
            proj_name = parameters[1].valueAsText
            outputPath, projName, fgdb = self.get_proj_info(proj_name)
            arcpy.AddWarning("Renaming the project does not rename the files and folders.")
            maintenance.package_project.rename_project(proj_name, parameters[5].valueAsText, PROJECT_FILE)
        elif parameters[0].valueAsText == "Remove Project Name":
            arcpy.AddWarning("Removing the project does not delete the files and folders.")
            for proj_name in parameters[2].values:
                maintenance.package_project.remove_project(proj_name, PROJECT_FILE)
        elif parameters[0].valueAsText == "Remove Project Name and Delete from Disk":
            arcpy.AddWarning("The project will be removed from the disk.")
            for proj_name in parameters[2].values:
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                outputPath, projName, fgdb = self.get_proj_info(proj_name)
                success = maintenance.package_project.remove_project_from_disk(aprx, outputPath)
                if success is True:
                    maintenance.package_project.remove_project(proj_name, PROJECT_FILE)
        elif parameters[0].valueAsText == "Remove Scenario Name":
            proj_name = parameters[1].valueAsText
            outputPath, projName, fgdb = self.get_proj_info(proj_name)
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            for scenario_name in parameters[4].values:
                self.schema_info["field_name_scenario_name"]
                maintenance.package_project.remove_scenario_from_disk(scenario_name, scenario_table, self.schema_info["field_name_scenario_name"])
        elif parameters[0].valueAsText == "Remove Scenario Name and Delete from Disk":
            proj_name = parameters[1].valueAsText
            outputPath, projName, fgdb = self.get_proj_info(proj_name)
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            for scenario_name in parameters[4].values:
                self.schema_info["field_name_scenario_name"]
                aprx = arcpy.mp.ArcGISProject("CURRENT")
                maintenance.package_project.remove_scenario_from_disk(scenario_name, scenario_table,
                                                                    self.schema_info["field_name_scenario_name"],
                                                                    aprx=aprx, projectFolder=outputPath, deleteFromDisk=True)
        elif parameters[0].valueAsText == "Rename Scenario":
            proj_name = parameters[1].valueAsText
            outputPath, projName, fgdb = self.get_proj_info(proj_name)
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            scenario_name = parameters[3].valueAsText
            maintenance.package_project.rename_scenario_from_disk(outputPath, scenario_name, scenario_table, self.schema_info["field_name_scenario_name"], self.schema_info["field_name_scenario_gdb"], parameters[5].valueAsText)
        elif parameters[0].valueAsText == "Export Project as Zip Archive":
            arcpy.AddMessage("Closing all maps to avoid lock files.")
            aprx = arcpy.mp.ArcGISProject("CURRENT")
            # Close all open map views
            aprx.closeViews("MAPS")
            aprx.closeViews("LAYOUTS")
            maintenance.package_project.create_zip_of_project(outputPath, outputPath.parent)
        elif parameters[0].valueAsText == "Import Folder as Project":
            outputPath = Path(parameters[7].valueAsText)
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            maintenance.package_project.import_projfolder(outputPath, fgdb, PROJECT_FILE)
        elif parameters[0].valueAsText == "Import Zip Archive as Project":
            if parameters[6].value:
                outputPath = Path(parameters[8].valueAsText)
                maintenance.package_project.import_archive(Path(parameters[6].valueAsText), outputPath, PROJECT_FILE)

        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        parameters[1].filter.list = list(self.projects.keys())
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""


        return
    
    
class path_checker:

    """
    Computes shortest route paths between origin and destination within a scenario network.

    Creates polyline feature class representations of shortest path for route visualization.

    Parameters:
        out_directory (DEFolder): Project folder.
        scenarios (GPString): Scenario under analysis.
        scenarioModes (GPString): Single travel mode label.
        networkType (GPString, multiValue): Type of network ('prenetwork' or 'postnetwork').
        origin_id (GPString): Origin node identifier.
        destination_id (GPString): Destination node identifier.

    Side Effects:
        - Writes shortest path polylines to scenario geodatabase.
        - May create feature classes if they do not exist.
        - Inserts descriptive attributes such as mode and network info.

    Usage:
        User specifies origin and destination IDs, along with mode and network options,
        to generate route geometry.

    Exceptions:
        Raises errors on missing network files or failed insertions to feature classes.

    Example:
        Compute pedestrian route between origin ID '100' and destination ID '200'.
    """
    def __init__(self):
        """
        Initialize path_checker tool label, description, and category.
        """
        self.label = "3G. Trace Shortest Path Between Two Network Nodes"
        self.description = ""
        self.category = "3 - Analysis/Accessibility Measures"
        self.schema_info = load_schema()
        self.settings_info = load_json_settings()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
    

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        scenarioModes = arcpy.Parameter(
            displayName="Scenario Modes",
            name="scenarioModes",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarioModes.filter.list = list(self.settings_info["mode_name_matching"].keys())
        scenarioModes.value = list(self.settings_info["mode_name_matching"].keys())[0]
        params.append(scenarioModes)

        networkType = arcpy.Parameter(
            displayName="Network Type",
            name="networkType",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue = True)
        networkType.filter.list = ["prenetwork", "postnetwork"]
        networkType.value = "prenetwork"
        params.append(networkType)

        origin_id = arcpy.Parameter(
            displayName="Origin ID",
            name="origin_id",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(origin_id)

        destination_id = arcpy.Parameter(
            displayName="Destination ID",
            name="destination_id",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        params.append(destination_id)
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):
        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")
        
        return

    
    def create_fc(self, scenario_fgdb, desc):
        from static_tools import helper_functions
        arcpy.AddMessage("creating shortest path feature class in the scenario file geodatabase")
        path_fc = helper_functions.drop_add_featureclass(scenario_fgdb, "shortest_paths", "POLYLINE", desc.spatialReference)
        helper_functions.drop_add_field(path_fc, "from_id", "TEXT")
        helper_functions.drop_add_field(path_fc, "to_id", "TEXT")
        helper_functions.drop_add_field(path_fc, "mode", "TEXT")
        helper_functions.drop_add_field(path_fc, "network", "TEXT")
        # helper_functions.drop_add_field(path_fc, "path_info", "TEXT", field_length=500)
        helper_functions.drop_add_field(path_fc, "fft", "DOUBLE")

    def execute(self, parameters, messages):

        import pickle
        import numpy as np
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        mode_lbl = parameters[2].valueAsText
        networktype = parameters[3].valueAsText
        origin_id = parameters[4].valueAsText
        dest_id = parameters[5].valueAsText
        #modes = parameters[2].values

        projName = outputPath.name.replace("_project", "")
        scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
        
        mode = None
        if mode_lbl == "Personal Vehicle":
            mode = self.schema_info["field_name_vehicle_mode"]
        elif mode_lbl == "Freight Truck":
            mode = self.schema_info["field_name_truck_mode"]
        elif mode_lbl == "Bicycle":
            mode = self.schema_info["field_name_bicycle_mode"]
        elif mode_lbl == "Pedestrian":
            mode = self.schema_info["field_name_pedestrian_mode"]
        elif mode_lbl == "Low Stress Bicycle":
            mode = self.schema_info["field_name_p_bicycle_mode"]
        elif mode_lbl == "Low Stress Pedestrian":
            mode = self.schema_info["field_name_p_pedestrian_mode"]

        allowed_types = [t.strip().lower() for t in str(networktype).split(";") if t.strip()]
        arcpy.AddMessage(f"Network types to try: {allowed_types}")

        for net_type in allowed_types:
            arcpy.AddMessage(f"Trying network type: {net_type}")
            path_fc = scenario_fgdb / self.schema_info["fc_name_shortest_paths"]
            
            desc = arcpy.Describe(str(scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]))

            if arcpy.Exists(str(path_fc)):
                already_computed = False
                with arcpy.da.SearchCursor(str(path_fc), ["from_id", "to_id", "mode", "network"]) as sc:
                    for row in sc:
                        if row[0] == origin_id and row[1] == dest_id and row[2] == mode and row[3] == net_type:
                            already_computed = True
                            break
                if already_computed:
                    arcpy.AddMessage("Shortest path already computed, skipping")
                    continue
            else:
                self.create_fc(scenario_fgdb, desc)

            network_fn = [row[0] for row in arcpy.da.SearchCursor(str(scenario_fgdb / self.schema_info["fc_network_table"]), [self.schema_info["field_name_network_filename"], self.schema_info["field_name_network_mode"], self.schema_info["field_name_network_prepost"]]) if row[1] == mode and row[2] == net_type] 
            
            arcpy.AddMessage(f"Looking for network file: {network_fn}")

            if len(network_fn) == 1: #if there is a network file for the mode and pre/post network type, load it
                desc = arcpy.Describe(str(scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]))
                #arcpy.AddMessage(f"Exists {arcpy.Exists(str(scenario_fgdb / 'shortest_paths'))}")
                arcpy.env.workspace = str(scenario_fgdb)
                
                with open(outputPath / scenario_name / network_fn[0], 'rb') as f: #load the network class from the file
                    nc = pickle.load(f)
                arcpy.AddMessage(f"Finding shortest path between {origin_id} and {dest_id}")
                sp = nc.find_path_between_origin_and_destination(origin_id, dest_id) #find the shortest path between the origin and destination using the network class
                
                if sp is None:
                    arcpy.AddError("No path found.")
                else:
                    # Map external IDs to internal graph indices
                    try:
                        origin_idx = nc.node_id_to_index[origin_id]
                        dest_idx   = nc.node_id_to_index[dest_id]
                    except KeyError as e:
                        raise ValueError(f"Node ID {e} not found in network mapping") from e
                    length = nc.find_distances([origin_idx], [dest_idx])
                    if isinstance(length, (list, tuple, np.ndarray)):
                        # If somehow a 1-element array, extract the scalar
                        length = float(np.asarray(length).flatten()[0])
                    arcpy.AddMessage(sp)
                    arcpy.AddMessage(path_fc)
                    arcpy.AddMessage(f"Length of path: {length} seconds")
                    origins = {row[1]:row[0] for row in arcpy.da.SearchCursor(str(scenario_fgdb/self.schema_info["fc_name_origin_nodes"]), ["SHAPE@", self.schema_info["field_name_origin_id"]])} #get the origins from the connectors nodes feature class
                    junctions = {row[1]:row[0] for row in arcpy.da.SearchCursor(str(scenario_fgdb/self.schema_info["fc_name_integrated_nodes"]), ["SHAPE@", self.schema_info["field_name_node_id"]])} #get the junctions from the osm junctions feature class
                    if sp[0] in origins: # if the first point in the shortest path is an origin, use the origin point
                        pnts = [origins[sp[0]]] + [junctions[nid] for nid in sp[1:]] # add the origin point to the start of the path, and then add the rest of the junction points
                    else:
                        pnts = [junctions[nid] for nid in sp] # if the first point in the shortest path is not an origin, use the junctions
                    arcpy.AddMessage("Making polyline from path")
                    arr = arcpy.Array([p.centroid for p in pnts]) # create an array of points from the path
                    pl = arcpy.Polyline(arr, desc.spatialReference) # create a polyline from the array of points
                    try:
                        with arcpy.da.InsertCursor(str(path_fc), ["SHAPE@", "from_id", "to_id", "mode", "network", "fft"]) as ic:
                            ic.insertRow([pl, origin_id, dest_id, mode, net_type, length]) # insert the polyline into the shortest paths feature class
                    except:
                        
                        try:
                            with arcpy.da.InsertCursor(str(path_fc), ["SHAPE@", "from_id", "to_id", "mode", "network", "fft"]) as ic:
                                ic.insertRow([pl, origin_id, dest_id, mode, net_type, length]) # insert the polyline into the shortest paths feature class
                        except Exception as e:
                            arcpy.AddError(f"Error creating shortest path feature class or adding shortest path... {e}")
                    del origins
                    del junctions
                    del nc

            else:
                arcpy.AddError(f"No file found for {mode_lbl} and {networktype} in {scenario_name}")
        
        # now add to map
        # first remove existing sp if on map
        p = arcpy.mp.ArcGISProject('CURRENT')
        m = p.activeMap
        for l in m.listLayers("Shortest Path*"):
            m.removeLayer(l)        
        # now add back to map
        fc_to_add = str(scenario_fgdb / self.schema_info["fc_name_shortest_paths"])
        # first the prenetwork version
        if 'prenetwork' in allowed_types:
            l = m.addDataFromPath(fc_to_add)
            l.definitionQuery = f"network = 'prenetwork' And from_id = '{origin_id}' And to_id = '{dest_id}'"
            l.name = "Shortest Path - Prenetwork"
            sym = l.symbology
            sym.updateRenderer("SimpleRenderer")
            sym.renderer.symbol.outlineColor = {'RGB': [130, 130, 130, 100]}
            sym.renderer.symbol.outlineWidth = 1.5
            l.symbology = sym
        # next the postnetwork version
        if 'postnetwork' in allowed_types:
            l = m.addDataFromPath(fc_to_add)
            l.definitionQuery = f"network = 'postnetwork' And from_id = '{origin_id}' And to_id = '{dest_id}'"
            l.name = "Shortest Path - Postnetwork"
            sym = l.symbology
            sym.updateRenderer("SimpleRenderer")
            sym.renderer.symbol.applySymbolFromGallery("Dashed 2:2")
            sym.renderer.symbol.outlineColor = {'RGB': [56, 168, 0, 100]}
            sym.renderer.symbol.outlineWidth = 1.5        
            l.symbology = sym
        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return



class add_layers:

    def __init__(self):
        """
        Initialize tool label, description, category for report generation.
        """
        self.label = "Add Scenario Data to a Map"
        self.description = ""
        self.category = "Maintenance"
        self.file_path = Path(__file__).parents[0]
        self.schema_info = load_schema()
        self.settings_info = None
        self.settings_info = load_json_settings()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        self.report_settings = None
        self.report_settings = load_colors()

    def getParameterInfo(self):
        """Define the tool parameters."""
        params = []
        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        scenarios = arcpy.Parameter(
            displayName="Scenario",
            name="scenarios",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        scenarios.filter.list = []
        params.append(scenarios)

        createMap = arcpy.Parameter(
            displayName="Create New Map",
            name="createMap",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input")
        createMap.value = True
        params.append(createMap)

        baseLayers = arcpy.Parameter(
            displayName="Layers",
            name="baseLayers",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        baseLayers.filter.list = ["Integrated Network Ways", 
                                 "Integrated Network Nodes",
                                 "Scenario Network Ways",
                                 "Scenario Network Nodes",
                                 "Census Blocks",
                                 "Origin Nodes"]
        
        params.append(baseLayers)

        poistr = self.settings_info.get("poi_categories_as_string", "")
        poiLayers = arcpy.Parameter(
            displayName="Points of Interest",
            name="poiLayers",
            datatype="GPString",
            parameterType="Required",
            direction="Input",
            multiValue=True)
        poiLayers.filter.list = [cat.strip() for cat in poistr.split("|") if cat.strip()]

        
        params.append(poiLayers)

        return params


    def updateParameters(self, parameters):


        if parameters[0].altered and not parameters[0].hasBeenValidated:
            proj_name = parameters[0].valueAsText
            outputPath = Path(self.projects[proj_name]["path"])
            projName = outputPath.name.replace("_project", "")
            fgdb = outputPath / f"{projName}_data.gdb"
            scenario_table = fgdb / self.schema_info["fc_scenario_table"]
            if arcpy.Exists(str(scenario_table)):
                scenarios = [row[0] for row in arcpy.da.SearchCursor(str(scenario_table), [self.schema_info["field_name_scenario_name"]])]
                if len(scenarios) == 0:
                    parameters[1].setErrorMessage("Create a scenario for your project first.")
                    parameters[1].value = "Create a scenario for your project first."
                else:
                    parameters[1].filter.list = scenarios
                    parameters[1].value = scenarios[0]
            else:
                parameters[1].setErrorMessage("Create a scenario for your project first.")
        
        return


    
    def add_layer(self, lyrx_path, fc_name, fgdb, m, layer_name):
        lyrx = arcpy.mp.LayerFile(str(lyrx_path))
        cp = {'dataset': fc_name, 'workspace_factory': 'File Geodatabase', 'connection_info': {'database': str(fgdb)}}
        lyrx.updateConnectionProperties(None, cp)
        _layer = m.addLayer(lyrx,"TOP")[0]
        _layer.name = layer_name

    def replacements(self, string_value, poi_field_map=None):
        if poi_field_map and string_value in poi_field_map:
            return poi_field_map[string_value]
            
        for r in ["\\", " ", "/", "-"]:
            string_value = string_value.replace(r, "_")
        return string_value.lower()
    
    def execute(self, parameters, messages):

        import matplotlib.colors
        proj_name = parameters[0].valueAsText
        outputPath = Path(self.projects[proj_name]["path"])
        scenario_name = parameters[1].valueAsText
        scenario_fgdb = outputPath / scenario_name / f"{scenario_name}.gdb"
        if scenario_fgdb.exists() is False:
            arcpy.AddError("Scenario file geodatabase not found.")

        proj = arcpy.mp.ArcGISProject("CURRENT")
        m = proj.activeMap
        if parameters[2].value is True:
            m = proj.createMap(f"TrACKIT {scenario_name}")

        #integrated_nodes_for_analysis.lyrx
        #origin_nodes.lyrx
        #area_census_blocks_projected.lyrx
        #integrated_network_for_analysis.lyrx
        if m is not None:
            for lyr_type in parameters[3].values:
                if lyr_type == "Integrated Network Ways":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_integrated_network"])) is True:
                        self.add_layer(self.file_path / "integrated_network_for_analysis.lyrx",
                                    self.schema_info["fc_name_integrated_network"],
                                    scenario_fgdb, m, lyr_type)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
                if lyr_type == "Integrated Network Nodes":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_integrated_nodes"])) is True:
                        self.add_layer(self.file_path / "integrated_nodes_for_analysis.lyrx",
                                    self.schema_info["fc_name_integrated_nodes"],
                                    scenario_fgdb, m, lyr_type)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
                if lyr_type == "Census Blocks":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_census_block_prj"])) is True:
                        self.add_layer(self.file_path / "area_census_blocks_projected.lyrx",
                                    self.schema_info["fc_name_census_block_prj"],
                                    scenario_fgdb, m, lyr_type)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
                if lyr_type == "Origin Nodes":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_origin_nodes"])) is True:
                        self.add_layer(self.file_path / "origin_nodes.lyrx",
                                    self.schema_info["fc_name_origin_nodes"],
                                    scenario_fgdb, m, lyr_type)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
                if lyr_type ==  "Scenario Network Ways":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_scenario_ways"])) is True:
                        lyr = arcpy.MakeFeatureLayer_management(scenario_fgdb / self.schema_info["fc_name_scenario_ways"], lyr_type).getOutput(0)
                        m.addLayer(lyr)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
                if lyr_type ==  "Scenario Network Nodes":
                    if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_scenario_nodes"])) is True:
                        lyr = arcpy.MakeFeatureLayer_management(scenario_fgdb / self.schema_info["fc_name_scenario_nodes"], lyr_type).getOutput(0)
                        m.addLayer(lyr)
                    else:
                        arcpy.AddWarning(f"Missing {lyr_type}")
            categories = parameters[4].values
            
            if len(categories) > 0:
                arcpy.AddMessage("Adding points of interest layers.")
                pois_fc_path = scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"]
                if arcpy.Exists(str(scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"])) is True:
                    raw_colors = self.report_settings.get("colors_for_categories", [])
                    base_colors = list(raw_colors.values()) if isinstance(raw_colors, dict) else list(raw_colors)
                    import managers
                    sm = managers.settingsManager(outputPath, scenario_name=scenario_name)
                    poi_field_map = sm.settings_info.get("poi_field_map", {})
                    for idx, poi_type in enumerate(categories):
                        fieldName = self.replacements(poi_type, poi_field_map)
                        dq = f"{fieldName.lower()} = 1"

                        make_lyr = arcpy.management.MakeFeatureLayer(str(pois_fc_path), f"{poi_type}", where_clause=dq).getOutput(0)
                        pois_layer = m.addLayer(make_lyr, "TOP")[0]
                        pois_layer.transparency = 50
                        pois_layer.name = f"{poi_type} POIs"
                        pois_symbology = pois_layer.symbology
                        pois_symbology.renderer.symbol.applySymbolFromGallery("Circle 1")
                        hex_poi_type = base_colors[idx] if idx < len(base_colors) else "#808080"
                        rgba = [int(x*255) for x in matplotlib.colors.to_rgb(hex_poi_type)] + [100]
                        #arcpy.AddMessage(hex_poi_type)
                        #arcpy.AddMessage(rgba)
                        # Example: Changing to a SimpleRenderer
                        if hasattr(pois_symbology, 'renderer'):
                            #symbology.updateRenderer("SimpleRenderer")
                            renderer = pois_symbology.renderer
                            renderer.symbol.color = {"RGB":rgba} # Red color with 100% opacity
                            renderer.symbol.outlineColor = {"RGB": [0, 0, 0, 0]} # Black outline
                            renderer.symbol.size = 4
                            renderer.symbol.angle = 0
                        pois_layer.symbology = pois_symbology
            m.openView()

        return


class redownload_osmdata:
    
    def __init__(self):
        """Initialize tool label, description, category and prepare variables."""

        self.label = "Redownload Project OSM Files"
        self.description = ""
        self.ProjFolder = ""
        self.category = "Maintenance"
        self.schema_info = load_schema()
        self.projects = maintenance.package_project.get_project_data(PROJECT_FILE)
        self.loaded_defaults = False

    def getParameterInfo(self):
        """Define the tool parameters."""

        params = []

        directory = arcpy.Parameter(
            displayName="Existing Project",
            name="out_directory",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        directory.filter.list = list(self.projects.keys())
        params.append(directory)

        filetype = arcpy.Parameter(
            displayName="OSM Data Types",
            name="filetype",
            datatype="GPString",
            parameterType="Required",
            direction="Input")
        filetype.filter.list = ["All required .osm files", "Ways / Network data ('_ways.osm')", "Points of Interest ('_poi.osm')", "Water Features ('_water.osm')"]
        params.append(filetype)
        return params

    def isLicensed(self):
        """Set whether the tool is licensed to execute."""
        return True

    def updateParameters(self, parameters):

        return




    def execute(self, parameters, messages):
        """The source code of the tool."""


        from static_tools import helper_functions
        from messenger import custMessenger
        from messenger import custTypes
        import data_downloader
        import data_osm_processor
        reload(data_downloader)

        outName = parameters[0].valueAsText

        if outName and outName != "":
            projObj = self.projects[outName]
            projectFolder = Path(projObj["path"])
            fgdb = projectFolder / f"{outName}_data.gdb"
            centroid_y = float(projObj["latitude"])
            centroid_x = float(projObj["longitude"])
            radius_destination = float(projObj["radius"])
            ll_lat, ll_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, -1*radius_destination, -1*radius_destination)
            ur_lat, ur_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, radius_destination, radius_destination)

            fileType = parameters[1].value
            messages = custMessenger(custTypes.ARCPYMESSAGE)
            if fileType in ["Ways / Network data ('_ways.osm')", "All required .osm files"]:
                messages.send_message("Downloading ways.")
                dl = data_downloader.osm_overpass_ways(projectFolder, messages)
                waysxml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)
                if waysxml is None:
                    arcpy.AddWarning("Failed to download ways data.")

            if fileType in ["Points of Interest ('_poi.osm')", "All required .osm files"]:
                messages.send_message("Downloading POI.")
                dl = data_downloader.osm_overpass_poi(projectFolder, messages)
                poixml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)
                if poixml is None:
                    arcpy.AddWarning("Failed to download POI data.")
            if fileType in ["Water Features ('_water.osm')", "All required .osm files"]:
                messages.send_message("Downloading water.")
                dl = data_downloader.osm_overpass_water(projectFolder, messages)
                waterxml = dl.download_data_bbox(ll_lat, ll_long, ur_lat, ur_long, outName)
                if waterxml is not None:
                    project_polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(ll_long, ll_lat),
                                        arcpy.Point(ur_long, ll_lat),
                                        arcpy.Point(ur_long, ur_lat),
                                        arcpy.Point(ll_long, ur_lat),
                                        arcpy.Point(ll_long, ll_lat),]), spatial_reference=arcpy.SpatialReference(4326))

                    
                    pwater = data_osm_processor.process_OSM_water(projectFolder, waterxml, fgdb, project_polygon, messages)
                    pwater.separate_osm_data()
                else:
                    arcpy.AddWarning("Failed to download POI data.")

        return

    def postExecute(self, parameters):
        """This method takes place after outputs are processed and
        added to the display."""

        return