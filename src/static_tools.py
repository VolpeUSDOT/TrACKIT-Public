import numpy as np
import arcpy
from pathlib import Path
import math
import re
import uuid

class GeographicCoordinateSystemError(Exception):
    def __init__(self,message="Need a projected coordinate system to proceed."):
        self.message = message
        super().__init__(self.message)

class CoordinateSystemMismatchError(Exception):
    def __init__(self,message="Layers do not have the same coordinate system."):
        self.message = message
        super().__init__(self.message)

class FeatureClassDoesNotExistError(Exception):
    def __init__(self,message="The supplied feature class does not exist."):
        self.message = message
        super().__init__(self.message)

class FieldDoesNotExistError(Exception):
    def __init__(self,message="The supplied field name does not exist in the feature class."):
        self.message = message
        super().__init__(self.message)

class WorkspaceDoesNotExistError(Exception):
    def __init__(self,message="The supplied workspace does not exist."):
        self.message = message
        super().__init__(self.message)

class random_id():
    
    @staticmethod
    def create_random_id(prefix:str, existing:set, append=False):
        if isinstance(existing, list):
            existing = set(existing)
        new_id = prefix + str(uuid.uuid1()).split("-")[0]
        if new_id in existing:
            return random_id.create_random_id(prefix, existing, append)
        else:
            if append:
                existing.add(new_id)
            return new_id
            
class helper_functions(object):

			

        
    STATE_LABELS = ['Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut', 'Delaware', 'District of Columbia',
     'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine',
     'Maryland', 'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada',
     'New Hampshire', 'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma',
     'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah',
     'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming']

    STATE_ABBREVIATIONS = ['AL', 'AK', 'AZ','AR', 'CA', 'CO', 'CT',  'DE', 'DC','FL', 'GA', 'HI','ID', 'IL', 'IN', 'IA', 'KS', 'KY',
             'LA',  'ME', 'MD', 'MA','MI', 'MN', 'MS','MO',  'MT', 'NE','NV','NH','NJ','NM','NY','NC', 'ND',  
             'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA',  'WA','WV', 'WI',  'WY']


    @staticmethod
    def sanitize_field_name(cat:str, cutoff:int=50):
        import re
        cat = cat.lower()
        cat = re.sub(r'[^a-z0-9_]+', '_', cat)  # replace any non-alphanumeric/underscore with underscore
        cat = re.sub(r'_+', '_', cat)  # collapse multiple underscores
        cat = cat.strip('_')  # trim leading/trailing underscores
        return cat[:cutoff] 

    @staticmethod
    def offset_lat_lon( lat, lon, offset_miles_north, offset_miles_east):
        """
        Offsets latitude and longitude by miles.
        
        Args:
            lat (float): Original latitude in decimal degrees.
            lon (float): Original longitude in decimal degrees.
            offset_miles_north (float): Miles to move north (+) or south (-).
            offset_miles_east (float): Miles to move east (+) or west (-).
        
        Returns:
            (new_lat, new_lon): Tuple of floats, offset coordinates in decimal degrees.

        """
        # Constants
        miles_per_degree_lat = 69.0  # approx miles per degree latitude
        
        # Convert latitude offset
        delta_lat = offset_miles_north / miles_per_degree_lat
        
        # Calculate miles per degree longitude at this latitude
        miles_per_degree_lon = 69.0 * math.cos(math.radians(lat))
        delta_lon = offset_miles_east / miles_per_degree_lon
        
        new_lat = lat + delta_lat
        new_lon = lon + delta_lon
        
        return new_lat, new_lon
    
    
    @staticmethod
    def get_wgs84_sr():
        return arcpy.SpatialReference(4326)

    @staticmethod
    def get_abbrv_to_state_dict():
        return {x:y for x,y in zip(helper_functions.STATE_ABBREVIATIONS,helper_functions.STATE_LABELS)}

    @staticmethod
    def get_state_to_abbrv_dict():
        return {y:x for x,y in zip(helper_functions.STATE_ABBREVIATIONS,helper_functions.STATE_LABELS)}

    @staticmethod
    def round_place(n,place=1000):
        """
        Rounds number to place.
        Args:
            n (float): number to change
            place (int): what place to round to
        Returns:
            float: rounded numbers
        """
        return int(math.ceil(n / place)) * place

    @staticmethod
    def tool_project_version_check(projFGDB:Path, version:str):
        ver = [row[0] for row in arcpy.da.SearchCursor(str(projFGDB / "project_centroid"), ["tool_version"])][0]
        if ver == version:
            return True
        else:
            return False

    @staticmethod
    def drop_add_field(featureClass:Path,field_name:str,field_type:str,add_index:bool=False,field_length=None,
                       field_precision=None,field_scale=None,index_name:str=None,index_unique:bool=None,field_alias:str=None, nullable=True)->bool:
        """
        Adds a field. If it exists, deletes the field and then adds it.
        Args:
            featureClass (pathlib.Path): path to feature class
            add_index (bool): add an index for the field. Need to provide index name
            field properties

        Returns:
            bool: True
        """
        if field_alias is None:
            field_alias = field_name
        try:
            if nullable:
                arcpy.management.AddField(str(featureClass),field_name,field_type,field_precision,field_scale,field_length,field_alias=field_alias)
            else:
                arcpy.management.AddField(str(featureClass),field_name,field_type,field_precision,field_scale,field_length,field_alias=field_alias, field_is_nullable = "NON_NULLABLE")
        except:
            arcpy.AddMessage(f"Deleting existing field: {field_name}")
            arcpy.management.DeleteField(str(featureClass),field_name)
            arcpy.management.AddField(str(featureClass),field_name,field_type,field_precision,field_scale,field_length,field_alias=field_alias)
            if nullable:
                arcpy.management.AddField(str(featureClass),field_name,field_type,field_precision,field_scale,field_length,field_alias=field_alias)
            else:
                arcpy.management.AddField(str(featureClass),field_name,field_type,field_precision,field_scale,field_length,field_alias=field_alias, field_is_nullable = "NON_NULLABLE")
        
        if add_index:
            try:
                if index_name==None:
                    index_name = field_name + "_index"
                if index_unique == None:
                    index_unique = False
                arcpy.management.AddIndex(str(featureClass),field_name,index_name,index_unique)
            except:
                pass
                
        return True

    @staticmethod
    def drop_add_featureclass_with_template(workspace:Path, featureClassName:str,templatePath:Path,featureClassType:str,sr:arcpy.SpatialReference,oid_type:str="32_BIT")->Path:
        """
        Deletes feature class if exists and creates it.
        Args:
            workspace (pathlib.Path): workspace path
            featureClassName (str): name of the feature class
            templatePath(pathlib.Path): path to template feature class
            featureClassType (str): POINT, POLYLINE, POLYGON
            sr (SpatialReference): spatial reference for the feature classf

        Returns:
            Path: feature class path
        """
        if arcpy.Exists(str(workspace/featureClassName)):
            arcpy.management.Delete(str(workspace/featureClassName))
        result = arcpy.management.CreateFeatureclass(str(workspace),featureClassName,featureClassType,template=str(templatePath),spatial_reference=sr,oid_type=oid_type).getOutput(0)
        return Path(result)


    @staticmethod
    def drop_add_featureclass(workspace:Path, featureClassName:str, featureClassType:str, sr:arcpy.SpatialReference,oid_type:str="32_BIT")->Path:
        """
        Deletes feature class if exists and creates it.
        Args:
            workspace (pathlib.Path): workspace path
            featureClassName (str): name of the feature class
            featureClassType (str): POINT, POLYLINE, POLYGON
            sr (SpatialReference): spatial reference for the feature class

        Returns:
            Path: feature class path
        """
        if arcpy.Exists(str(workspace/featureClassName)):
            arcpy.management.Delete(str(workspace/featureClassName))
        result = arcpy.management.CreateFeatureclass(str(workspace),featureClassName,featureClassType,spatial_reference=sr,oid_type=oid_type).getOutput(0)
        return Path(result)

    @staticmethod
    def drop_add_fgdb_table(workspace:Path, tableName:str)->Path:
        """
        Deletes feature class if exists and creates it.
        Args:
            workspace (pathlib.Path):file geodatabase workspace
            tableName (str): name of the feature class
        Returns:
            Path: table path
        """
        if arcpy.Exists(str(workspace/tableName)):
            arcpy.management.Delete(str(workspace/tableName))
        result = arcpy.management.CreateTable(str(workspace),tableName).getOutput(0)
        return Path(result)

    @staticmethod
    def drop_add_fgdb(workspace:Path,fgdbName:str)->Path:
        """
        Deletes file geodatabase if exists and creates it.
        Args:
            workspace (pathlib.Path): folder
            fgdbName (str): name with gdb extension
        Returns:
            Path: fgdb path
        """
        if arcpy.Exists(str(workspace/f"{fgdbName}.gdb")):
            arcpy.management.Delete(str(workspace/f"{fgdbName}.gdb"))
        result = arcpy.management.CreateFileGDB(str(workspace),fgdbName).getOutput(0)
        return Path(result)

    @staticmethod
    def clean_field_name(field_name):
        """
        Converts a string to an ArcGIS-compatible field name.

        Args:
            field_name: The string to convert.

        Returns:
            A string that is a valid ArcGIS field name.

        #written by ai
        """
        # Replace non-alphanumeric characters with underscores
        cleaned_name = re.sub(r'[^a-zA-Z0-9_]', '_', field_name)
        
        # Remove leading numbers
        cleaned_name = re.sub(r'^[0-9]+', '', cleaned_name)
        
        # Ensure the name starts with a letter or underscore
        if not re.match(r'^[a-zA-Z_]', cleaned_name):
            cleaned_name = '_' + cleaned_name
        
        # Truncate to 64 characters (ArcGIS limit)
        cleaned_name = cleaned_name[:64]
        
        return cleaned_name

    @staticmethod
    def pandas_to_arcpy_fields(df, integer_type="LONG", float_type="DOUBLE"):
        matches = {}
        for col, dt in zip(df.columns, df.dtypes):
            clean_name = helper_functions.clean_field_name(col)
            if dt == object:
                matches[col] = {"featureClass":None,"field_name":clean_name,"field_type":"TEXT","field_length":255}
            elif dt in (int, np.int64):
                matches[col] = {"featureClass":None,"field_name":clean_name,"field_type":integer_type}
            elif dt in (float, np.float64):
                matches[col] = {"featureClass":None,"field_name":clean_name,"field_type":float_type}
        return matches

    @staticmethod
    def list_fields_for_cursor(featureClass:Path,startFields=["SHAPE@","OID@"])->list:
        """
        Creates a list of fields without OBJECTID, Shape, or Shape_Length. Use startFields to place field names in the beginning.
        Args:
            featureClass (Path): path to feature class
            startFields (list): fields to include
        Returns:
            list: fields in feature class.
        """
        fields = arcpy.ListFields(str(featureClass))

        if startFields == None:
            startFields = []
        
        startFields += [f.name for f in fields]
        startFields.remove("OBJECTID")
        startFields.remove("Shape")
        startFields.remove("Shape_Length")
        return startFields


    @staticmethod
    def check_for_GCS(featureClass:Path)->bool:
        """
        Check if the feature class's coordinate system is projected or geographic
        Args:
            featureClass (Path): path to feature class
        Returns:
            bool: True - if coordinate reference system is geographic; False - if not geographic
        
        """
        if arcpy.Exists(str(featureClass)):
            sr = arcpy.Describe(str(featureClass)).spatialReference
            if sr.type == "Geographic":
                return True
            else:
                return False
        else:
            False
    
    @staticmethod
    def check_for_sameproj(featureClass1:Path,featureClass2:Path)->bool:
        """
        Quick check if to feature classes are in the same projection.
        Args:
            featureClass1 (Path): path to first feature class
            featureClass2 (Path): path to second feature class
        Returns:
            bool: True - if they are the same; False - if they are not the same
        Raises:
            FeatureClassDoesNotExistError: if feature class does not exist.

        """

        if arcpy.Exists(str(featureClass1)):
            if arcpy.Exists(str(featureClass2)):
                sr1 = arcpy.Describe(str(featureClass1)).spatialReference
                sr2 = arcpy.Describe(str(featureClass2)).spatialReference
                if sr1.factoryCode == sr2.factoryCode:
                    return True
                else:
                    return False
            else:
                raise FeatureClassDoesNotExistError()
        else:
            raise FeatureClassDoesNotExistError()



    @staticmethod
    def match_crs(featureClassBase:Path,featureClass:Path,workspace:Path)->str:
        """
        Project feature class to same projection as base.
        Args:
            featureClassBase (Path): this will provide the coordinate reference system.
        Returns:
            str: path to projected feature class
        Raises:
            FeatureClassDoesNotExistError: if feature class does not exist.
            WorkspaceDoesNotExistError: if workspace does not exist.
        """
        fn = workspace / featureClass.stem
        
        if arcpy.Exists(str(workspace)):
            if arcpy.Exists(str(featureClassBase)):
                sr1 = arcpy.Describe(str(featureClassBase)).spatialReference
                #sr2 = arcpy.Describe(str(featureClass2)).spatialReference
                res = arcpy.management.Project(str(featureClass),str(fn),sr1).getOutput(0)
                return res
            else:
                raise FeatureClassDoesNotExistError()
        else:
            raise WorkspaceDoesNotExistError()


    @staticmethod
    def direction(compass_angle) -> str:
        if compass_angle < 22.5:
            return "North"
        if compass_angle >= 22.5 and compass_angle < 67.5:
            return "Northeast"
        if compass_angle >= 67.5 and compass_angle < 112.5:
            return "East"
        if compass_angle >= 112.5 and compass_angle < 157.5:
            return "Southeast"
        if compass_angle >= 157.5 and compass_angle < 202.5:
            return "South"
        if compass_angle >= 202.5 and compass_angle < 247.5:
            return "Southwest"
        if compass_angle >= 247.5 and compass_angle < 292.5:
            return "West"
        if compass_angle >= 292.5 and compass_angle < 337.5:
            return "Northwest"
        if compass_angle >= 337.5:
            return "North"

    @staticmethod
    def linear_angle_cardinal(featureClass:str)->tuple:
        """
        Description custom version of Esri's linear directional mean:
        https://pro.arcgis.com/en/pro-app/2.8/tool-reference/spatial-statistics/h-how-linear-directional-mean-spatial-statistics-w.htm
        
        Args:
            featureClass (str): path to polyline feature class
        
        Returns:
            tuple: List of compass angles, list of cardinal directions
        Raises:
            GeographicCoordinateSystemError: if feature class uses GCS
        """
        if arcpy.Exists(featureClass):
            isgcs = helper_functions.check_for_GCS(featureClass)
            if isgcs == True:
                raise GeographicCoordinateSystemError
            with arcpy.da.SearchCursor(featureClass,["SHAPE@"]) as sc:
                lines = [row[0] for row in sc]
            compass_angles = []
            compass_direc = []
            ldm = []
            for cl in lines:
                seg_order = []
                for part in cl:
                    for pnt in part:
                        seg_order.append([pnt.X,pnt.Y])
                seg_order = np.array(seg_order)
                seg_delta = np.diff(seg_order,axis=0)
                seg_theta = np.arctan2(seg_delta[:,0],seg_delta[:,1])
                #print(seg_theta)
                seg_theta_deg = np.mean(np.rad2deg(seg_theta))
                #print(seg_theta_deg)
                if seg_theta_deg>=0:
                    compass_angles.append(seg_theta_deg)
                elif seg_theta_deg <0:
                    compass_angles.append(360 + seg_theta_deg)
            #     seg_theta = np.arctan2(seg_delta[:,0],seg_delta[:,1])
            #     seg_theta = np.arctan(seg_delta[:,0]/seg_delta[:,1])
            #     #compass_angles.append(np.degrees(seg_theta)[0])
            #     seg_cos = np.cos(np.arctan2(seg_delta[:,0],seg_delta[:,1]))
            #     seg_sin = np.sin(np.arctan2(seg_delta[:,0],seg_delta[:,1]))
            #     seg_ldm = np.arctan(np.sum(seg_sin)/np.sum(seg_cos))
            #     #seg_ldm = np.rad2deg(seg_ldm)
            #     ldm.append(seg_ldm)
                
            #     if seg_sin>= 0 and seg_cos > 0:
            #         compass_angles.append(np.rad2deg(seg_ldm))
            #     elif np.sum(seg_sin)>= 0 and np.sum(seg_cos) < 0:
            #         compass_angles.append(180 - np.rad2deg(seg_ldm))
            #     elif np.sum(seg_sin)< 0 and np.sum(seg_cos) > 0:
            #         compass_angles.append(360 - np.rad2deg(seg_ldm))
            #     elif np.sum(seg_sin)< 0 and np.sum(seg_cos) < 0:
            #         compass_angles.append(180 + np.rad2deg(seg_ldm))
            #     else:
            #        compass_angles.append(None)
            compass_direc = [helper_functions.direction(ca) for ca in compass_angles]
            return compass_angles,compass_direc

    @staticmethod
    def overall_orientation_cardinal(featureClass:str)->tuple:
        """
        Description custom version of Esri's linear directional mean:
        https://pro.arcgis.com/en/pro-app/2.8/tool-reference/spatial-statistics/h-how-linear-directional-mean-spatial-statistics-w.htm
        
        Args:
            featureClass (str): path to polyline feature class
        Returns:
            tuple: List of compass angles, list of cardinal directions
        Raises:
            GeographicCoordinateSystemError: if feature class uses GCS
        """
        if arcpy.Exists(featureClass):
            isgcs = helper_functions.check_for_GCS(featureClass)
            if isgcs == True:
                raise GeographicCoordinateSystemError
            with arcpy.da.SearchCursor(featureClass,["SHAPE@"]) as sc:
                lines = [row[0] for row in sc]
            compass_angles = []
            compass_direc = []
            for cl in lines:
                seg_order = []
                for pnt in [cl.firstPoint,cl.lastPoint]:
                    seg_order.append([pnt.X,pnt.Y])
                seg_order = np.array(seg_order)
                seg_delta = np.diff(seg_order,axis=0)
                seg_theta = np.arctan2(seg_delta[:,0],seg_delta[:,1])
                #print(seg_theta)
                seg_theta_deg = np.mean(np.rad2deg(seg_theta))
                #print(seg_theta_deg)
                if seg_theta_deg>=0:
                    compass_angles.append(seg_theta_deg)
                elif seg_theta_deg <0:
                    compass_angles.append(360 + seg_theta_deg)
            compass_direc = [helper_functions.direction(ca) for ca in compass_angles]
            return compass_angles,compass_direc


    @staticmethod
    def point_angles_degrees(center_point:np.array,points:np.array)->list:
        """
        Description custom version of Esri's linear directional mean:
        https://pro.arcgis.com/en/pro-app/2.8/tool-reference/spatial-statistics/h-how-linear-directional-mean-spatial-statistics-w.htm
        
        Args:
            center_point (tuple): x,y
            points (np.array): array of coordinates
        
        Returns:
            list: compass angles

        """
        delta = center_point - points
        sigma = np.rad2deg(np.arctan2(delta[:,0],delta[:,1]))
        compass_angles = list(np.where(sigma<0,sigma+360,sigma))
        return compass_angles


    @staticmethod
    def inbound_outbound(inboundPoint:arcpy.Point,featureClass:str):
        """
        Todo:
            Not implemented. Needs testing.
        Raises:
            GeographicCoordinateSystemError: if feature class uses GCS
        """
        if arcpy.Exists(featureClass):

            isgcs = helper_functions.check_for_GCS(featureClass)
            if isgcs == True:
                raise GeographicCoordinateSystemError

            with arcpy.da.SearchCursor(featureClass,["SHAPE@"]) as sc:
                lines = [row[0] for row in sc]
            in_out = []
            for cl in lines:
                start_dist = inboundPoint.distanceTo(cl.firstPoint)
                end_dist = inboundPoint.distanceTo(cl.lastPoint)
                delta_y = cl.firstPoint.Y - cl.lastPoint.Y
                delta = start_dist / end_dist
                #if delta> -100 and delta < 100:
                    #in_out.append("UNK")
                if start_dist < end_dist:
                    in_out.append("OUTBOUND")
                elif start_dist > end_dist:
                    in_out.append("INBOUND")
            if len(lines)==len(in_out):
                return in_out
            else:
                print("problem")
    @staticmethod
    def convert_rows_columns_to_coordinates(xmin:float,ymax:float,cw:float,ch:float,row:int,column:int,dx=0,dy=0)->tuple:
        """
        Converts the column and row to an x and y coordinate
        Args:
            xmin (float): the minimum x value of the raster (upper left)
            ymax (float): the maximum y value of the raster (upper left)
            cw (float): cell width 
            ch (float): cell height
            row (int): index of the row
            column (int): index of the column
            dx (float): offset if needed in the x direction
            dy (float): offset if needed in the y direction
        Returns:
            tuple: the x and y coordinates"""

        return (xmin + (.5 * cw) + (column * cw)+dx,ymax - (.5 * ch) - (row * ch)+dy)

    @staticmethod
    def process_raster_layer_values_and_coords(raster_pth:Path)->tuple:
        """
            Process one raster layer to retreive values and coords with data. Skips No data.
        Args:
            raster_pth (Path): path to the raster layer
        Returns:
            tuple: Value of each cell (numpy array), Coords of each cell (numpy array)
        Raises:
            GeographicCoordinateSystemError: if feature class uses GCS
        """
        if helper_functions.check_for_GCS(raster_pth) == True:
            raise GeographicCoordinateSystemError()

        r_c = arcpy.Raster(str(raster_pth))

        sr_c = r_c.spatialReference.factoryCode
        
        xmin = r_c.extent.XMin
        ymax = r_c.extent.YMax
        cw = r_c.meanCellWidth
        ch = r_c.meanCellHeight

        #load into numpy arrays for analysis

        #create raster cell iterator, much faster than raster to numpy function, skip the nodata cells.
        with arcpy.sa.RasterCellIterator({'rasters':[r_c],'skipNoData':[r_c]}) as rci_skip:
            values = np.array([ rci_skip[i, j] for i, j in rci_skip])
            coords = np.array([helper_functions.convert_rows_columns_to_coordinates(xmin,ymax,cw,ch,i,j) for i, j in rci_skip])

        return values, coords


    @staticmethod
    def dms_to_dd(str_dms:str)->tuple:
        """
        Converts a string of latitude and longitude in degrees minutes seconds to decimal degrees.
        Args:
            str_dms (str): Uses the string format 42° 11' 3.171" N / 73° 24' 11.666" W
        Returns:
            tuple: latitude and longitide
        """
        
        lat_base = str_dms.split(" / ")[0]
        long_base = str_dms.split(" / ")[1]
        output = []
        for x in [lat_base,long_base]:
            re_pattern = r"(\d+)\s?\°\s?(\d+)\s?\'\s?(\d{1,}\.?\,?\d{0,}?)\"\s?(N|W|S|E)"
            result = re.search(re_pattern,x)
            minutes = float(result.group(2)) / 60
            seconds = float(result.group(3)) / 3600
            degrees =float(result.group(1))+minutes+seconds
            if result.group(4) in ("W","S"):
                degrees*=-1
            output.append(degrees)
        return output


    @staticmethod
    def geodesic(lat1:float,lon1:float,lat2:float,lon2:float)->float:
        """
        Geodesic distance
        Args:
            lat1 (float)
            lon1 (float)
            lat2 (float)
            lon2 (float)

        returns
            float: distance in meters.
        """
        import math
        R = 6371000
        phi1 = lat1 * math.pi / 180
        phi2 = lat2 * math.pi / 180
        deltaphi = (lat2 - lat1) * math.pi / 180
        deltalambda = (lon2 - lon1) * math.pi / 180
        a = math.sin(deltaphi / 2) * math.sin(deltaphi/2) + math.cos(phi1) * math.cos(phi2) * math.sin(deltalambda/2) * math.sin(deltalambda/2)
        c = 2 * math.atan2(math.sqrt(a),math.sqrt(1-a))
        d = R * c
        return d

    @staticmethod
    def lines_to_points(lines:list):
        """
        Lines to all the points.
        Args:
            lines - list of of arcpy.polylines
        returns
            np.array of xy coordinates
        """
        points = []
        for v in lines:
            l=v[0]
            if l:
                for part in l:
                    for pnt in part:
                        points.append([pnt.X,pnt.Y])
        return np.array(points)
    
    @staticmethod
    def bounding_box(pnts):
        """
        Calculate the bounding box to find the upper left side of the lines.
        Args:
            pnts - np.array of coordinates
        returns
            bbox - arcpy.polyline of the line's bounding box
            halfline - arcpy.polyline of the line's halfway point
            ulline - arcpy.polyline of the points upper left
        """
        xmin = np.min(pnts[:,0])
        xmax = np.max(pnts[:,0])
        ymin = np.min(pnts[:,1])
        ymax = np.max(pnts[:,1])
        dy = np.abs(ymax-ymin)
        dx = np.abs(xmax-xmin)
        if dy > dx:
            half = dx*.5+xmin
            halfline = arcpy.Polyline(arcpy.Array([arcpy.Point(half,ymin),arcpy.Point(half,ymax)]))
            ulline = arcpy.Polyline(arcpy.Array([arcpy.Point(xmin,ymax),arcpy.Point(xmax,ymax)]))
        else:
            half = dy*.5+ymin
            halfline = arcpy.Polyline(arcpy.Array([arcpy.Point(xmin,half),arcpy.Point(xmax,half)]))
            ulline = arcpy.Polyline(arcpy.Array([arcpy.Point(xmin,ymin),arcpy.Point(xmin,ymax)]))
        bbox = arcpy.Polyline(arcpy.Array([arcpy.Point(xmin,ymin),arcpy.Point(xmin,ymax),arcpy.Point(xmax,ymax),arcpy.Point(xmax,ymin)]))
        return bbox,halfline,ulline
    
    @staticmethod
    def copy_line(line,reverse=False):
        """Make a copy of the line. Flip it if reverse == True
        Args:
            line - arcpy.Polyline to be copied
            reverse - boolean, True to reverse the order of the line
        """
        parts = arcpy.Array()
        for part in line:
            partlst = []
            for pnt in part:
                partlst.append(pnt)
            if reverse:
                partlst = partlst[::-1]
            parts.append(arcpy.Array(partlst))
        return arcpy.Polyline(parts)
    
    @staticmethod
    def sort_lines_ul(lines:list):
        """
        Sorts the lines for a particular order.
        Args:
            lines - list of tuples of (arcpy.Polylines, FID\OID) to sort in order
        returns:
            list of lines in new order
        """
       
        #_lines = [[row[0],row[1]] for row in arcpy.da.SearchCursor(str(featureClass),["SHAPE@","OID@"])]
        pnts = helper_functions.lines_to_points(lines)
        _,_,ulline = helper_functions.bounding_box(pnts)
        #sorted_lines = self.sort_lines(ulline)
        _index = polyline_kdtree_index(lines)
        _index.build_tree()
        orig_index_to_sort_index = {}
        closest = []
        newlines = []
        for i,v in enumerate(lines):
            ln=v[0]
            res = _index.tree.query_ball_point([ln.firstPoint.X,ln.firstPoint.Y],0)
            if len(res)==1:
                closest.append((i,False))
            res = _index.tree.query_ball_point([ln.lastPoint.X,ln.lastPoint.Y],0)
            if len(res)==1:
                closest.append((i,True))
        mindist = 10000^10
        minindx = -1
        rev = False
        for i,r in closest:
            cp = lines[i][0]
            _,_,fpd,_ = ulline.queryPointAndDistance(cp.firstPoint)
            _,_,lpd,_= ulline.queryPointAndDistance(cp.lastPoint)
            if fpd < lpd:
                if fpd<mindist:
                    mindist = fpd
                    minindx = i
                    rev=r
            else:
                if lpd<mindist:
                    mindist = lpd
                    minindx = i
                    rev=r
        start_line = helper_functions.copy_line(lines[minindx][0],rev)
        newidx = 0
        newlines.append([start_line,0,minindx])
        orig_index_to_sort_index[minindx] = newidx
        current_line = start_line
        total_length = current_line.length
        current_index = minindx
        while len(newlines)<=len(lines):
            indc = _index.tree.query_ball_point((current_line.lastPoint.X,current_line.lastPoint.Y),r=0)
            matches = _index.point_to_polyline_index[indc]
            matches = matches[matches!=current_index]
            if len(matches)==0:
                break
            match = matches[0]

            next_line = lines[match][0]
            rev = False
            a = np.array([[next_line.lastPoint.X,next_line.lastPoint.Y],[next_line.firstPoint.X,next_line.firstPoint.Y]])
            b = np.array([[current_line.lastPoint.X,current_line.lastPoint.Y]])
            if np.sqrt(np.sum(np.square(a[0]-b))) < np.sqrt(np.sum(np.square(a[1]-b))):
                rev = True
            new_line = helper_functions.copy_line(next_line,rev)
            newlines.append([new_line,0,match])
            newidx +=1
            orig_index_to_sort_index[match] = newidx
            current_line = new_line
            current_index = match
            total_length += current_line.length


        return newlines
    

    
    @staticmethod
    def extent_as_string_latlong_url(fc:Path)->str:
        """
        Converts extent to latitude and longitude and returns as a string separated by commas from min x and y to max x and y
        args
            fc (Path): path to feature class
        returns
            str formatted as minx,miny,maxx,maxy
        """
        wgs84 = helper_functions.get_wgs84_sr()
        desc = arcpy.Describe(str(fc))
        ext = desc.extent
        ll = arcpy.PointGeometry(arcpy.Point(ext.XMin,ext.YMin),desc.spatialReference)
        ur = arcpy.PointGeometry(arcpy.Point(ext.XMax,ext.YMax),desc.spatialReference)
        llprj = ll.projectAs(wgs84)
        urprj = ur.projectAs(wgs84)
        return "{},{},{},{}".format(llprj.firstPoint.X,llprj.firstPoint.Y,urprj.firstPoint.X,urprj.firstPoint.Y)

    @staticmethod
    def shp_extent_as_string_latlong_url(shp,sr)->str:
        """
        Converts extent to latitude and longitude and returns as a string separated by commas from min x and y to max x and y
        args
            fc (Path): path to feature class
            sr (spatial reference): spatial reference of the shape
        returns
            str formatted as minx,miny,maxx,maxy
        """
        wgs84 = arcpy.SpatialReference(4326)
        ext = shp.extent
        ll = arcpy.PointGeometry(arcpy.Point(ext.XMin,ext.YMin),sr)
        ur = arcpy.PointGeometry(arcpy.Point(ext.XMax,ext.YMax),sr)
        llprj = ll.projectAs(wgs84)
        urprj = ur.projectAs(wgs84)
        return "{},{},{},{}".format(llprj.firstPoint.X,llprj.firstPoint.Y,urprj.firstPoint.X,urprj.firstPoint.Y)
    
    @staticmethod
    def extent_as_string(fc:Path)->str:
        """
        Returns extent as a string separated by spaces from min x and y to max x and y
        args
            fc (Path): path to feature class
        returns
            str formatted as minx miny maxx maxy
        """
        wgs84 = arcpy.SpatialReference(4326)
        desc = arcpy.Describe(str(fc))
        rect = "{} {} {} {}".format(desc.extent.XMin,desc.extent.YMin,desc.extent.XMax,desc.extent.YMax)
        return rect
    
    @staticmethod
    def extent_as_polygon(fc:Path)->str:
        """
        Returns extent as a polygon
        args
            fc (Path): path to feature class
        returns
            Polygon
        """

        ext = arcpy.Describe(str(fc)).extent
        ll = arcpy.Point(ext.XMin,ext.YMin)
        lr = arcpy.Point(ext.XMax,ext.YMin)
        ur = arcpy.Point(ext.XMax,ext.YMax)
        ul = arcpy.Point(ext.XMin,ext.YMax)
        arr = arcpy.Array([ll,lr,ur,ul,ll])
        return arcpy.Polygon(arr)

    


    @staticmethod
    def shp_extent_as_string(shp)->str:
        """
        Returns extent as a string separated by spaces from min x and y to max x and y
        args
            fc (Path): path to feature class
        returns
            str formatted as minx miny maxx maxy
        """
        ext = shp.extent
        rect = "{} {} {} {}".format(ext.XMin,ext.YMin,ext.XMax,ext.YMax)
        return rect
    

    @staticmethod
    def shp_extent_to_polygon(shp)->str:
        """
        Returns extent as a string separated by spaces from min x and y to max x and y
        args
            fc (Path): path to feature class
        returns
            str formatted as minx miny maxx maxy
        """

        ext = shp.extent
        ll = arcpy.Point(ext.XMin,ext.YMin)
        lr = arcpy.Point(ext.XMax,ext.YMin)
        ur = arcpy.Point(ext.XMax,ext.YMax)
        ul = arcpy.Point(ext.XMin,ext.YMax)
        arr = arcpy.Array([ll,lr,ur,ul,ll])
        return arcpy.Polygon(arr)

    @staticmethod
    def get_hemisphere(latitude:float)->str:
        """
            Determines the hemisphere (N or S) based on the latitude
            author: gary.baker@dot.gov
        Args:
            latitude (float): latitude in decimal degrees
        Returns:
            str: N or S
        """

        if float(latitude) < 0:
            return 'S'
        return 'N'
    
    @staticmethod
    def get_utm_zone(longitude:float)->int:
        """
            Determines the UTM zone based on longitude
            author: gary.baker@dot.gov
        Args:
            longitude (float): longitude in decimal degrees
        Returns:
            int: zone
        """
        utmZone = int((math.floor((float(longitude) + 180)/6) % 60)+ 1)
        return utmZone
    
    @staticmethod
    def get_utm_spatialreference(latitude:float=None,longitude:float=None,zone:int=None,hemisphere:str=None,returnSR=True)->int:
        """
            Determines the Esri spatial reference id
            author: gary.baker@dot.gov
        Args:
            latitude (float): latitude in decimal degrees. If None then the script will use hemisphere value.
            longitude (float): longitude in decimal degrees. If None then the script will use zone.
            zone (int): pre calculated zone
            hemisphere (str): N or S
            returnSR: Return spatial reference object if True
        Returns:
            int: spatial reference id
            arcpy.SpatialReference: if returnSR is true
        """

        if latitude is not None:
            hemisphere = helper_functions.get_hemisphere(latitude)
        
        if longitude is not None:
            zone = helper_functions.get_utm_zone(longitude)
        
        
        if zone < 1 or zone > 60:
            print(zone)
            raise Exception("invalid zone specified")

        srid = None

        if (hemisphere == 'N'):
            srid = 32600
        elif (hemisphere == 'S'):
            srid = 32700
        else:
            raise Exception("invalid hemisphere")

        srid += zone

        if returnSR:
            return arcpy.SpatialReference(srid)


        return srid