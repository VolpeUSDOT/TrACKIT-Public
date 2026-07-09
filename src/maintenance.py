import arcpy
import json
import yaml
from pathlib import Path
import os
from messenger import custMessenger, custTypes
import shutil
from managers import settingsManager
from static_tools import helper_functions

class upgrader(settingsManager):
    def __init__(self, projectFolder:Path):
        """
            Parent class 
            Args:
                projectFolder (Path): folder where the project data is written.
                projFGDB (Path): project file geodatabase where the processed OSM data is written.
            Returns:
                processor class object or child of the processor class.
        """

        super().__init__(projectFolder, scenario_name=None, ignore_centroid=True)

        self.scenario_names = []
        self.get_scenario_names()

    def get_scenario_names(self):
        namefield = self.schema_info["field_name_scenario_name"]
        self.scenario_names = [row[0] for row in arcpy.da.SearchCursor(str(self.scenario_table), [namefield])]


class update_alpha_to_beta(upgrader):
    def __init__(self, projectFolder):
        super().__init__(projectFolder)


    def alter_field(self, fgdb, fcname, oldname, newname, alias=None):
        if alias is None:
            alias = newname
        arcpy.AlterField_management(str(fgdb / fcname), oldname, newname, alias)

    def alter_fc_name(self, fgdb, oldname, newname):
        if arcpy.Exists(str(fgdb/oldname)):
            arcpy.Rename_management(str(fgdb/oldname), str(fgdb/newname))

    def upgrade_database(self):
        field_changes = [('osmid','original_id'),('road','vehicle'),('walk','pedestrian'),('p_walk','p_pedestrian'),('speed_ped','speed_pedestrian'),('speed_auto','speed_vehicle'),('fft_auto','fft_vehicle'),('from_osmid','from_node_id'),('to_osmid','to_node_id'),('linkosmid','orig_link_id'),('way_id','original_way_id'),('fft_ped','fft_pedestrian'),('node_osmid','node_poi_id'),('poi_osmid','poi_original_id')]
        fc_changes = [("project_area_census_blocks", "area_census_blocks"), ("project_area_census_blocks_prj","area_census_blocks_projected"), ('osm_ways','base_network_ways'),('osm_junctions','base_network_nodes'),('osm_pois','pois_nodes'),('osm_water','water_features'),('osm_water_utm','water_features_utm'),('osm_ways_for_analysis','integrated_network_for_analysis'),('osm_junctions_for_analysis','integrated_nodes_for_analysis'),('connectors_nodes','origin_nodes')]
        for s in self.scenario_names:
            scenario_gdb = self.project_folder / s / f"{s}.gdb"
            if arcpy.Exists(str(scenario_gdb)) is True:
                for dirpath, dirnames, filenames in arcpy.da.Walk(str(scenario_gdb), datatype="FeatureClass"):
                    for filename in filenames:
                        fields = [f.name for f in arcpy.ListFields(str(scenario_gdb / filename))]
                        for o, n in field_changes:
                            if o in fields:
                                self.alter_field(scenario_gdb, filename, o, n)
        for dirpath, dirnames, filenames in arcpy.da.Walk(str(self.project_fgdb), datatype="FeatureClass"):
            for filename in filenames:
                fields = [f.name for f in arcpy.ListFields(str(self.project_fgdb / filename))]
                for o, n in field_changes:
                    if o in fields:
                        self.alter_field(self.project_fgdb, filename, o, n)
            
        for ofc, nfc in fc_changes:
            for s in self.scenario_names:
                scenario_gdb = self.project_folder / s / f"{s}.gdb"
                if arcpy.Exists(str(scenario_gdb / ofc)) is True:
                    self.alter_fc_name(scenario_gdb, ofc, nfc)
            if arcpy.Exists(str(self.project_fgdb / ofc)) is True:
                self.alter_fc_name(self.project_fgdb, ofc, nfc)


class update_water_features(upgrader):
    def __init__(self, projectFolder):
        super().__init__(projectFolder)

    def upgrade_database(self):
        from static_tools import helper_functions
        from data_osm_processor import process_OSM_water
        project_data = [[row[0], row[1], row[2]] for row in arcpy.da.SearchCursor(str(self.project_fgdb/ self.schema_info['fc_name_project_centroid']),
                                                                                  ["SHAPE@", self.schema_info['field_name_radius_dest'],
                                                                                   self.schema_info['field_name_project_name']])]
        if len(project_data)>0:
            pnt = project_data[0][0]
            radius_destination = project_data[0][1]
            project_name = project_data[0][2]
            centroid_y = pnt.centroid.Y
            centroid_x = pnt.centroid.X
            ll_lat, ll_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, -1*radius_destination, -1*radius_destination)
            ur_lat, ur_long =  helper_functions.offset_lat_lon(centroid_y, centroid_x, radius_destination, radius_destination)
            polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(ll_long, ll_lat),
                                        arcpy.Point(ur_long, ll_lat),
                                        arcpy.Point(ur_long, ur_lat),
                                        arcpy.Point(ll_long, ur_lat),
                                        arcpy.Point(ll_long, ll_lat),]), spatial_reference=arcpy.SpatialReference(4326))
            waterxml = self.project_folder / f"{project_name}_water.osm"
            pwater = process_OSM_water(self.project_folder, waterxml, self.project_fgdb, polygon, custMessenger(custTypes.ARCPYMESSAGE))
            pwater.separate_osm_data()

                
class package_project(object):
    @staticmethod
    def zip_folder(folder_path, output_zip_path):
        
        """
        Creates a zip archive from a specified folder.

        Args:
            folder_path (str): The path to the folder to be zipped.
            output_zip_path (str): The desired path and filename for the output zip archive.
        """
        import zipfile
        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(folder_path):
                arcpy.SetProgressor("step", f"Processing {len(files)} files",0, len(files), 1)
                for file in files:
                    if ".lock" not in file:
                        file_path = os.path.join(root, file)
                        # Calculate the relative path within the zip archive
                        arcname = os.path.relpath(file_path, folder_path)
                        zipf.write(file_path, arcname)
                        arcpy.SetProgressorPosition()

    @staticmethod
    def create_zip_of_project(in_proj_folder:Path, out_proj_folder:Path):
        archive_name = out_proj_folder / f'{in_proj_folder.name}_archive.zip'
        archive_format = 'zip'
        arcpy.AddMessage(archive_name)
        #arcpy.AddMessage(archive_format)
        arcpy.AddMessage(out_proj_folder)
        arcpy.AddMessage(in_proj_folder)
        #shutil.make_archive(archive_name, archive_format, str(in_proj_folder), str(out_proj_folder))
        package_project.zip_folder(in_proj_folder, archive_name)

    @staticmethod
    def import_archive(archive_path:Path, out_proj_folder:Path, proj_file_path:Path):
            
        import zipfile
        names = archive_path.name.replace("_project_archive.zip","")
        out_zip_folder = out_proj_folder / f"{names}_project"
        out_zip_folder.mkdir(exist_ok=True)
        with zipfile.ZipFile(str(archive_path), 'r') as zip_ref:
            # Extract all contents to the specified destination directory
            zip_ref.extractall(str(out_zip_folder))
        project_centroid_path = out_proj_folder / f"{names}_project" / f"{names}_data.gdb" / "project_centroid"
        project = {}
        with arcpy.da.SearchCursor(str(project_centroid_path), ["SHAPE@XY","project_name","utmepsg","radius_destination"]) as sc:
            for row in sc:
                project["name"] = row[1]
                project["utmepsg"] = row[2]
                project["radius"] = row[3]
                project["latitude"] = row[0][1]
                project["longitude"] = row[0][0]
        project["path"] = str(out_zip_folder)
        package_project.add_project(project, proj_file_path)

    @staticmethod
    def import_projfolder(proj_folder:Path, proj_fgdb:Path, proj_file_path:Path):
        project_centroid_path = proj_fgdb/ "project_centroid"
        project = {}
        with arcpy.da.SearchCursor(str(project_centroid_path), ["SHAPE@XY","project_name","utmepsg","radius_destination"]) as sc:
            for row in sc:
                project["name"] = row[1]
                project["utmepsg"] = row[2]
                project["radius"] = row[3]
                project["latitude"] = row[0][1]
                project["longitude"] = row[0][0]
        project["path"] = str(proj_folder)
        package_project.add_project(project, proj_file_path)

    @staticmethod
    def create_project_file(projects:list, filepath:Path):
        package_project.send_to_json_file(filepath, projects)

    @staticmethod
    # read JSON list, append a dict, write it back.
    def add_project(project:dict, filepath:Path):
        obj = package_project.get_json_data(filepath)
        exists = False
        for i, cp in enumerate(obj):
            if cp["name"] == project["name"]:
                if cp["path"] == project["path"]:
                    exists = True
                else:
                    raise Exception("Project name already exists, but at a different folder")
        if exists is True:
            obj[i] = project
        else:
            obj.append(project)
        package_project.send_to_json_file(filepath, obj)

    @staticmethod
    def rename_project(oldname, newname, filepath:Path):
        obj = package_project.get_json_data(filepath)
        updateidx = None
        for i,x in enumerate(obj):
            if x["name"] == oldname:
                updateidx = i
                break
        if updateidx is not None:
            obj[updateidx]["name"] = newname
        
        package_project.send_to_json_file(filepath, obj)

    @staticmethod
    def rename_scenario(oldname, newname, filepath:Path):
        obj = package_project.get_json_data(filepath)
        updateidx = None
        for i,x in enumerate(obj):
            if x["name"] == oldname:
                updateidx = i
                break
        if updateidx is not None:
            obj[updateidx]["name"] = newname
        
        package_project.send_to_json_file(filepath, obj)

    @staticmethod
    def remove_project(proj_name, filepath:Path):
        obj = package_project.get_json_data(filepath)
        removeidx = []
        for i,x in enumerate(obj):
            if x["name"] == proj_name:
                removeidx.append(i)
        for i in removeidx:
            del obj[i]
        package_project.send_to_json_file(filepath, obj)

    @staticmethod
    def get_project_data(filepath):
        obj = package_project.get_json_data(filepath)
        project_data = {p["name"]:{} for p in obj}
        for x in obj:
            project_data[x["name"]]= {k:v for k,v in x.items() if k!="name"}
        return project_data
    
    @staticmethod
    def get_json_data(pathToFile:Path)->list:
        """
        Gets json data from a path
        Args:
            pathToFile (pathlib.Path): path to the json file
        Returns:
           dict or list of json object
        """        
        with open(pathToFile, 'r', encoding="utf8") as openfile:
            json_obj = json.load(openfile)

        #if type(json_obj) is not list:
        #    raise Exception("JSON Data should be a list of objects...")
        
        return json_obj
    
    @staticmethod
    def send_to_json_file(pathToFile:Path,objectData:list)->Path:
        """
        Writes json to dictionary 
        Args:
            pathToFile (pathlib.Path): path to the json file
            objectData (list): list of dictionaries or dictionary object to be written
        Returns:
           dict of json object
        """        
        #if type(objectData) is not list:
        #    raise Exception("JSON Data should be a list of dictionaries...")
        
        with open(pathToFile, "w", encoding="utf8") as outfile:
            json.dump(objectData, outfile, ensure_ascii=False)

        return pathToFile

    @staticmethod
    def force_delete_lock_or_readonly(func, path, exc_info):
        import stat
        """Callback handler to force-delete stubborn or locked GIS files."""
        # Clear the read-only attribute if OS blocked it
        os.chmod(path, stat.S_IWRITE)
        try:
            func(path)
        except Exception as e:
            arcpy.AddWarning(f"Skipping or failed on file (Active Lock exists): {path} -> {e}")


    @staticmethod
    def remove_project_from_disk(aprx:arcpy.mp.ArcGISProject, projectFolder:Path):
        
        if projectFolder.exists() and projectFolder.is_dir():
            arcpy.AddMessage("Closing maps and layouts to avoid issues with locked files.")
            active_view = aprx.activeView
            if active_view is not None:
                aprx.closeViews("MAPS")
                aprx.closeViews("LAYOUTS")
            try:
                arcpy.Delete_management(str(projectFolder), data_type="Folder")
                arcpy.AddMessage(f"{projectFolder} removed from disk.")
                if active_view is not None:
                    try:
                        active_view.openView()
                    except:
                        pass
                return True
            except Exception:
                try:
                    arcpy.ClearWorkspaceCache_management()
                    shutil.rmtree(str(projectFolder), onexc=package_project.force_delete_lock_or_readonly)
                    arcpy.AddMessage(f"{projectFolder} removed from disk using fallback method.")
                    return True
                except Exception:
                    arcpy.AddWarning(f"Unable to remove {projectFolder}. Confirm that there are no active locks on the project folder. Close out of Windows Explorer, and close and Restart ArcGIS Pro.")
                    return False
        else:
            arcpy.AddMessage(f"The folder {projectFolder} was already missing from the disk. Proceeding to remove it from the project list.")
            return True
        
    @staticmethod
    def remove_scenario_from_disk(scenarioName:str, scenarioTable:Path, scenarioNameColumn:str,
                                    aprx:arcpy.mp.ArcGISProject=None, 
                                    projectFolder:Path=None, deleteFromDisk=False):
        removeScenario = False
        if deleteFromDisk is True:
            scenarioFolder = projectFolder / scenarioName
            if scenarioFolder.exists() and scenarioFolder.is_dir():
                arcpy.AddMessage("Closing maps and layouts to avoid issues with locked files.")
                active_view = aprx.activeView
                if active_view is not None:
                    aprx.closeViews("MAPS")
                    aprx.closeViews("LAYOUTS")
                try:
                    arcpy.Delete_management(str(scenarioFolder), data_type="Folder")
                    arcpy.AddMessage(f"{scenarioFolder} removed from disk.")
                    removeScenario = True
                    if active_view is not None:
                        try:
                            active_view.openView()
                        except:
                            pass
                except Exception:
                    try:
                        arcpy.ClearWorkspaceCache_management()
                        shutil.rmtree(str(scenarioFolder), onexc=package_project.force_delete_lock_or_readonly)
                        arcpy.AddMessage(f"{scenarioFolder} removed from disk using fallback method.")
                        removeScenario = True
                    except Exception:
                        arcpy.AddWarning(f"Unable to remove {scenarioFolder}. Confirm that there are no active locks on the scenario folder. Close out of Windows Explorer, and close and Restart ArcGIS Pro.")
                        return False
            else:
                arcpy.AddMessage(f"The folder {scenarioFolder} was already missing from the disk. Proceeding to remove it from the scenario table.")
                removeScenario = True
        else:
            removeScenario = True

        if removeScenario is True:
            with arcpy.da.UpdateCursor(str(scenarioTable), [scenarioNameColumn]) as uc:
                for row in uc:
                    if row[0] == scenarioName:
                        uc.deleteRow()
        return True
    
    @staticmethod
    def rename_scenario_from_disk(projFolder:Path, scenarioName:str, scenarioTable:Path, scenarioNameColumn:str, scenarioGDBColumn:str,newName:str):
        if (projFolder/scenarioName).exists():
            clean_new_name = helper_functions.clean_field_name(newName)
            if clean_new_name != newName:
                arcpy.AddMessage(f"Cleaning {newName} to {clean_new_name}")
            scenario_gdb = projFolder / scenarioName / f"{scenarioName}.gdb"

            new_gdb =  projFolder / scenarioName / f"{clean_new_name}.gdb"
            arcpy.AddMessage(f"Renaming {scenario_gdb} to {new_gdb}")

            arcpy.management.Rename(str(scenario_gdb), str(new_gdb), data_type="Workspace")

            arcpy.ClearWorkspaceCache_management()
            scenario_folder = projFolder / scenarioName
            new_folder = projFolder / clean_new_name
            arcpy.management.Rename(str(scenario_folder),
                str(new_folder),
                data_type="Folder"
            )
            with arcpy.da.UpdateCursor(str(scenarioTable), [scenarioNameColumn, scenarioGDBColumn]) as uc:
                for row in uc:
                    if row[0] == scenarioName:
                        row[0] = clean_new_name
                        row[1] = f"{clean_new_name}.gdb"
                        uc.updateRow(row)
            return True
        return False