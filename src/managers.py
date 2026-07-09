import yaml
from pathlib import Path
from static_tools import helper_functions
import re
import arcpy
import json
from messenger import custMessenger
from messenger import custTypes
import random
import string

class settingsManager(object):
    """Global load settings class"""

    def __init__(self, projectFolder:Path, scenario_name:str=None,
                 messages:custMessenger=None, ignore_centroid:bool=False):
        self.file_path = Path(__file__).parents[0]
        self.project_folder = projectFolder
        self.scenario_name = scenario_name

        self.load_schema()
        projName = self.project_folder.name.replace("_project", "")

        self.project_fgdb = self.project_folder / f"{projName}_data.gdb"
        self.scenario_table_name = self.schema_info["fc_scenario_table"]
        self.scenario_table = self.project_fgdb / self.scenario_table_name
        self.utmsr = None
        self.schema_info = None
        self.report_settings = None
        self.settings_info = None
        if messages is None:
            try:
                import arcpy
                self.messages = custMessenger(custTypes.ARCPYMESSAGE)
            except:
                self.messages = custMessenger(custTypes.PYLOGGING, str(self.project_folder, "PROCESS_LOG.txt"))
        else:
            self.messages = messages
        self.messages.send_message(self.file_path)

        self.load_report_settings()
        self.load_settings()
        self.getUTMepsg(ignore_centroid)

    def load_schema(self):
        """
            Loads the settings schema file, stores as schema_info variable
            Args:
                None
            Returns:
                None
        """
        
        with open(self.file_path / 'schema.yaml', 'r') as f:
            self.schema_info = yaml.load(f, Loader=yaml.Loader)

    
    def load_report_settings(self):
        """
            Loads the colors file, stores as report_settings variable
            Args:
                None
            Returns:
                None
        """
        with open(self.file_path / 'colors.json', 'r', encoding='UTF-8') as file:
            self.report_settings = json.load(file)

    def load_settings(self):
        """
            Loads the settings file, stores as settings_info variable
            Args:
                None
            Returns:
                None
        """
        if self.schema_info is None:
            self.load_schema()
            
        #NETWORK SETTINGS
        with open(self.file_path / 'settings.json', 'r', encoding='UTF-8') as file:
            self.settings_info = json.load(file)

        self.settings_info["poi_values_as_string"] = POICategoryManager.get_default_tag_values_as_string()
        self.settings_info["scenario_categories"] = []
        #POI SETTINGS
        if self.project_folder:
            poi_man = POICategoryManager(self.project_folder, self.project_fgdb)
            self.settings_info["abbrevs_for_categories"] = poi_man.get_category_short_name()
            self.settings_info["poi_field_map"] = poi_man.get_category_fields()
            if self.scenario_name is not None:
                if arcpy.Exists(str(self.scenario_table)):
                    fields = [self.schema_info["field_name_scenario_name"], self.schema_info["field_name_selected_poi_categories"]]
                    scenario_info = {row[0]:row[1] for row in arcpy.da.SearchCursor(str(self.scenario_table), fields)}
                    raw_cats = scenario_info.get(self.scenario_name, "")
                    if raw_cats:
                        self.settings_info["scenario_categories"] = [c.strip() for c in str(raw_cats).split("|") if c.strip()]
                    else:
                        self.settings_info["scenario_categories"] = []
            else:
                self.settings_info["scenario_categories"] = poi_man.get_categories()

    def getUTMepsg(self, ignore_centroid):
        if self.project_fgdb:
            pth = str(self.project_fgdb / self.schema_info["fc_name_project_centroid"])
            if arcpy.Exists(pth):
                epsg = [row[0] for row in arcpy.da.SearchCursor(pth, [self.schema_info["field_name_utm"]])][0]
                self.utmsr = arcpy.SpatialReference(epsg)
            else:
                if ignore_centroid:
                    self.utmsr = None
                else:
                    raise Exception("Missing the project centroid feature class. Did Step 1A complete successfully?")

BASE_CATEGORIES = """

#master category list
Category Names:
  - &cat_cultural Cultural facilities
  - &cat_public   Public institutions
  - &cat_nature   Parks and nature
  - &cat_grocery  Grocery stores
  - &cat_sports   Sports centers
  - &cat_retail   Retail
  - &cat_trans    Transportation
  - &cat_faith    Faith organizations
  - &cat_rest     Restaurants
  - &cat_hosp     Healthcare hospitals
  - &cat_health   Healthcare other
  - &cat_k12      Education K12 schools
  - &cat_hed      Education higher ed
  - &cat_child    Education childcare and preshool
  
Category Field Names:
  *cat_cultural: cultural_facilities
  *cat_public: public_institutions
  *cat_nature: parks_and_nature
  *cat_grocery: grocery_stores
  *cat_sports: sports_centers
  *cat_retail: retail
  *cat_trans: transportation
  *cat_faith: faith_organizations
  *cat_rest: restaurants
  *cat_hosp: health_hospitals
  *cat_health: health_other
  *cat_k12: education_k12
  *cat_hed: education_higher_ed
  *cat_child: education_childcare

Category Short Names:
  *cat_cultural: CUL
  *cat_public: PUB
  *cat_nature: PAR
  *cat_grocery: GRO
  *cat_sports: SPO
  *cat_retail: RET
  *cat_trans: TRA
  *cat_faith: FAI
  *cat_rest: RES
  *cat_hosp: HOS
  *cat_health: HEA
  *cat_k12: K12
  *cat_hed: HED
  *cat_child: CHI

#Rules for creating categories
Category Tag Match:
  *cat_trans:
    building: [airport_terminal, bus_station, station, train_station, transportation]
    amenity: [bicycle_rental, bus_station]
    highway: [bus_stop]
    public_transport: [stop_position]
    government: [transportation]

  *cat_cultural:
    building: [cinema, function_hall, museum, ruins, ship, theatre, zoo]
    amenity: [arts_centre, cinema, museum, theatre]
    tourism: [artwork, attraction, museum, ruins, theme_park, zoo]
    memorial: [memorial]
    observation_tower: ~

  *cat_health:
    amenity: [clinic, doctors, doctor]
    healthcare: [clinic, doctors, doctor]
    healthcare:speciality: ~
    emergency: [urgent_care]

  *cat_hosp:
    building: [hospital]
    amenity: [hospital]
    healthcare: [hospital]
    emergency: [hospital, "yes"]

  *cat_sports:
    building: [riding_hall, sports_centre, sports_hall, stadium, town_swiming_pool, yoga_studio]
    amenity: [clubhouse]
    flag:type: [athletic]
    leisure: [golf_course, ice_rink, sports_centre, sports_hall, stadium]

  *cat_retail:
    building: [atm, bank, commercial;retail, retail]
    amenity: [atm, bank, pharmacy, veterinary]
    shop: [chemist, clothes, department_store, doityourself, florist, garden_centre, general, hairdresser, laundry, mall, newsagent, optician, stationery, variety_store]
    amenity_1: [pharmacy]
    healthcare: [pharmacy]
    shop_1: [florist]
    beauty_shop: ~
    bicycle_shop: ~
    bookshop: ~
    car_dealership: ~
    computer_shop: ~
    furniture_shop: ~
    gift_shop: ~
    market_place: ~
    mobile_phone_shop: ~
    outdoor_shop: ~
    shoe_shop: ~
    sports_shop: ~
    toy_shop: ~
    video_shop: ~

  *cat_nature:
    natural: [beach, cave_entrance]
    surface: [beach]
    landuse: [nature_reserve, park, recreation_ground, cemetery, forest]
    leisure: [dog_park, nature_reserve, park, playground, recreation_ground]
    government: [park]
    amenity: [fountain]
    water: [fountain]

  *cat_grocery:
    building: [supermarket]
    shop: [bakery, beverages, butcher, convenience, supermarket, variety_store]
    cuisine: [bakery]
    craft: [bakery]

  *cat_public:
    building: [civic, community_centre, fire_station, government, Government_Facility, government_office, library, municipal, police, public, townhall]
    amenity: [camp_site, community_centre, courthouse, fire_station, library, police, post_office, public_building, townhall]
    tourism: [camp_site]
    flag:type: [municipal]
    government: [government, municipal, police]
    library: [public]
    diplomatic: [embassy]
    town_hall: ~

  *cat_faith:
    building: [Casa hermana, cathedral, chapel, church, convent, kingdom_hall, monastery, mosque, religious, synagogue, temple, yes;church]
    amenity: [monastery]
    religion: [buddhist, christian, hindu, jewish, muslim, sikh]
    flag:type: [religious]
    monastery:type: [convent, monastery]
    christian_anglican: ~
    christian_catholic: ~
    christian_evangelical: ~
    christian_lutheran: ~
    christian_methodist: ~
    christian_orthodox: ~
    christian_protestant: ~
    muslim_shia: ~
    muslim_sunni: ~

  *cat_rest:
    building: [brewery, dining_hall, restaurant]
    amenity: [bar, biergarten, cafe, fast_food, food_court, nightclub, pub, restaurant]
    cuisine: [cafe, fast_food, pub]
    craft: [brewery]
    amenity_1: [bar]

  *cat_k12:
    building: [school, yes;school]
    amenity: [school]
    site: [school]

  *cat_hed:
    building: [college, university, university_building, university;yes]
    amenity: [college, university]
    site: [university]
    building_1: [university]
    residential: [university]
    college: ~

  *cat_child:
    amenity: [kindergarten, childcare, nursery, preschool]
    education: [kindergarten, childcare, nursery, preschool]
    preschool: ["yes"]
    nursery: ["yes"]
    kindergarten: ["yes"]
    childcare: ["yes"]

#exclude these tags or tag values from the categories
Exclusion Tags:
  - { tag: "highway", val: "*", exception: "bus_stop" }
  - { tag: "construction", val: "*" }
  - { tag: "building", val: "construction" }
  - { tag: "disused", val: "yes" }
  - { tag: "disused:amenity", val: "*" }
  - { tag: "disused:leisure", val: "*" }
  - { tag: "disused:shop", val: "*" }
  - { tag: "disused:tourism", val: "*" }
  - { tag: "disused:building", val: "*" }
  - { tag: "amenity", val: "post_box" }
  - { tag: "amenity", val: "bicycle_parking" }
  - { tag: "amenity", val: "parking" }
  - { tag: "historic:amenity", val: "*" }
  - { tag: "abandoned:building:use", val: "*" }
  - { tag: "tourism", val: "information" }
  - { tag: "tourism", val: "picnic_site" }
  - { tag: "service", val: "siding" }
  - { tag: "service", val: "yard" }
  - { tag: "service", val: "spur" }
  - { tag: "service", val: "crossover" }
  - { tag: "public_transport", val: "station" }
  - { tag: "natural", val: "tree" }
  - { tag: "surveillance", val: "*" }


"""
class POICategoryManager:
    def __init__(self, project_folder:Path, project_fgdb:Path):
        self._project_folder = project_folder
        if type(self._project_folder) == str:
            self._project_folder = Path(self._project_folder)
        self._project_fgdb = project_fgdb

        if type(self._project_fgdb) == str:
            self._project_fgdb = Path(self._project_fgdb)
        self._file_path = Path(__file__).parents[0]
        #self._schema_info = settingsManager.load_schema(self._file_path)
        self._category_info = None
        self._category_tag_match = None
        self._category_names = None
        self._exclusions = None
        self._all_values = None
        self._category_field_name_map = None
        self._category_short_name_map = None
        self._yaml_file_name = 'settings_poi.yaml'
        self.load_yaml_file()

    def load_yaml_file(self):
        """Loads the settings_poi.yaml file"""

        yaml_file = self._project_folder / self._yaml_file_name
        if yaml_file.exists() is False:
            with open(yaml_file, "w", encoding="utf-8") as file:
                file.write(BASE_CATEGORIES)
        
        with open(yaml_file, 'r') as f:
            self._category_info = yaml.safe_load(f)

        if self._category_info:
            self._category_tag_match = self._category_info.get('Category Tag Match', {})
            self._category_names = self._category_info.get('Category Names', [])
            self._exclusions = self._category_info.get('Exclusion Tags', [])
            self._category_field_name_map = self._category_info.get("Category Field Names", {})
            self._category_short_name_map = self._category_info.get("Category Short Names", {})
            self._all_values = []
            for category_name, rules in self._category_tag_match.items():
                if rules:
                    for osm_k, expected_vals in rules.items():
                        if expected_vals is None:
                            self._all_values.append(osm_k)
                        else:
                            self._all_values += expected_vals
                if category_name not in self._category_short_name_map:
                    self._category_short_name_map[category_name] = self.create_short_name(category_name)
            self._all_values = list(set(self._all_values))

    
    #getters and setters

    def get_categories(self):
        """Returns a list of all the categories"""
        return self._category_names
    
    @staticmethod
    def get_default_categories():
        categories = yaml.safe_load(BASE_CATEGORIES)
        return categories.get('Category Names', [])

    def get_tag_values(self):
        """Returns a list of all the osm values"""
        return self._all_values

    @staticmethod
    def get_default_tag_values():
        category_info = yaml.safe_load(BASE_CATEGORIES)
        category_tag_match = category_info.get('Category Tag Match', {})
        all_values = []
        for category_name, rules in category_tag_match.items():
            if rules:
                for osm_k, expected_vals in rules.items():
                    if expected_vals is None:
                        all_values.append(osm_k)
                    else:
                        all_values += expected_vals
        return all_values
    
    @staticmethod
    def get_default_tag_values_as_string():
        all_values = POICategoryManager.get_default_tag_values()
        return "|".join(all_values)
        
    def get_category_fields(self):
        """Returns a dictionary of category name to field name"""
        return self._category_field_name_map

    def get_category_short_name(self):
        return self._category_short_name_map
    
    # clean up tools
    def create_field_name(self, category_name:str):
        if category_name not in self._category_field_name_map:
            self._category_field_name_map[category_name] = helper_functions.sanitize_field_name(category_name)


    def create_short_name(self, category_name:str):
        """Attempts to find a unique short name by iterating forwards and back then reverting to random numbers"""
        category_name = category_name.replace(" ", "").replace("_", "")
        short_names = [v for v in self._category_short_name_map.values()]
        short_name = category_name.upper()[:3]
        sn_check = short_name in short_names
        first_pos = 0
        second_pos = 1
        third_pos = 2
        str_len = len(category_name)
        direction = 1
        iterations = 0
        while sn_check:
            try:
                short_name = f"{category_name.upper()[first_pos]}{category_name.upper()[second_pos]}{category_name.upper()[third_pos]}"
                sn_check = short_name in short_names
            except:
                short_name = f"{category_name.upper()[random.randint(0, str_len-1)]}{category_name.upper()[random.randint(0, str_len-1)]}{category_name.upper()[random.randint(0, str_len-1)]}"
                sn_check = short_name in short_names
            if (third_pos >= str_len) or (third_pos==0):
                second_pos += direction
                if second_pos+1 >= str_len:
                    first_pos += direction
                    second_pos = first_pos+direction
                elif second_pos == 0:
                    second_pos = str_len - 1
                third_pos = second_pos + direction
            else:
                third_pos += direction
            if iterations > 100 and sn_check is True:
                short_name = f"{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}{random.choice(string.ascii_uppercase)}"
                sn_check = short_name in short_names
            iterations +=1
        return short_name


    def get_match(self, value:str, target_values):
        if target_values is None:
            return None
        
        if value is None:
            return None

        for k in target_values:
            if value.replace(" ","").casefold() == k.replace(" ","").casefold():
                return k
        return None
    
    # file operations
    def save(self):
        """Write out info and changes to the categories"""
        data = {
            'Exclusion Tags': self._exclusions,
            'Category Names': self._category_names,
            'Category Tag Match': self._category_tag_match,
            "Category Field Names": self._category_field_name_map,
            "Category Short Names": self._category_short_name_map
        }
        with open(self._project_folder / self._yaml_file_name, 'w') as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)



    def add_category_and_tags(self, category_name:str,
                              category_short_name:str=None,
                            osm_key:str=None, 
                            osm_value:str=None):
        """Update categories with new tags and values
            Args:
                category_name (str) - broad categorical name for POI
                osm_key (str) - (optional) tag key
                osm_value (str) - (optional) value for tag
            Returns:
                updates the internal files.
                if osm_key is None only the Category is added
                if osm_key is not None add the value is not None, the value is added to the list
                if osm_key is not None and the value is None, the value is set to None
        
        """
        #Add the category if it doesn't exist
        matched_category_name = self.get_match(category_name, self._category_tag_match)
        if  matched_category_name is None:

            self._category_tag_match[category_name] = None
            self._category_names.append(category_name)
            self.create_field_name(category_name)
            if category_short_name:
                self._category_short_name_map[category_name] = category_short_name
            else:
                self._category_short_name_map[category_name] = self.create_short_name(category_name)
            matched_category_name = category_name
        if osm_key:
            if self._category_tag_match[matched_category_name] is None:
                self._category_tag_match[matched_category_name] = {}
            matched_osm_key = self.get_match(osm_key, self._category_tag_match[matched_category_name])
            if matched_osm_key is not None:
                self._category_tag_match[matched_category_name][osm_key] = None
                matched_osm_key = osm_key
            matched_osm_value = self.get_match(osm_value, self._category_tag_match[matched_category_name][matched_osm_key])
            if matched_osm_value is None:
                if osm_value:
                    if self._category_tag_match[matched_category_name][matched_osm_key] is None:
                        self._category_tag_match[matched_category_name][matched_osm_key] = []
                    self._category_tag_match[matched_category_name][matched_osm_key].append(osm_value)
                else:
                    self._category_tag_match[matched_category_name][matched_osm_key] = None
        self.save()

    def remove_tag_from_category(self, category_name:str, osm_key:str, osm_value:str=None):
        """Remove values from categories
            Args:
                category_name (str) - broad categorical name for POI
                osm_key (str) - tag key
                osm_value (str) - (optional) value for tag
            Returns:
                updates the internal files.
                if osm_key is not None add the value is not None, the value is removed from the list
                if osm_key is not None and the value is None, the key is removed from the category
        
        """
        matched_category_name = self.get_match(category_name, self._category_tag_match)
        if matched_category_name is not None:
            if osm_key in self._category_tag_match[matched_category_name]:
                if osm_value:
                    if osm_value in self._category_tag_match[matched_category_name][osm_key]:
                        self._category_tag_match[matched_category_name][osm_key].remove(osm_value)
                else:
                    del self._category_tag_match[matched_category_name][osm_key]
        self.save()

    def remove_category(self, category_name):
        """Removes category_name from the tag matching and the category list"""
        matched_category_name = self.get_match(category_name, self._category_tag_match)
        if matched_category_name is not None:
            del self._category_tag_match[matched_category_name]
            self._category_names.remove(matched_category_name)
            del self._category_field_name_map[matched_category_name]
            del self._category_short_name_map[matched_category_name]
        self.save()

    def add_exclusion(self, tag_name:str, tag_value:str, exception=None):
        """Adds a new exclusion rule."""
        rule = {'tag': tag_name, 'val': tag_value}
        if exception:
            rule['exception'] = exception
        
        if rule not in self.exclusion_tags:
            self.exclusion_tags.append(rule)
        self.save()


    def remove_exclusion(self, tag_name:str, tag_value:str):
        """Removes an exclusion rule matching the key and value."""
        
        new_list = []
        for exc in self._exclusions:
            if exc['tag'].casefold() != tag_name.casefold() and exc['val'].casefold() != tag_value.casefold():
                new_list.append(exc)
        self._exclusions = new_list
        self.save()


    # Feature class operations
    def add_categories_as_fields(self, poi_fc:Path, category_name:str=None):
        """ Adds the categories to a feature class as fields. Assumes binary field type.
            category  is the alias of the field.
            if category_name is None, adds all categories as fields if they are not in the fc already
            if category_name is not None, verifies category exists and adds that field
        """
        
        existing_fields = [f.name for f in arcpy.ListFields(str(poi_fc))]
        
        if category_name is None:
            for k_category_name, field_name in self._category_field_name_map.items():
                if field_name not in existing_fields:
                    helper_functions.drop_add_field(poi_fc, field_name, "SHORT", field_alias = k_category_name)
        else:
            matched_category_name = self.get_match(category_name, self._category_tag_match)
            if matched_category_name is not None:
                field_name = self._category_field_name_map[matched_category_name]
                if field_name not in existing_fields:
                    helper_functions.drop_add_field(poi_fc, field_name, "SHORT", field_alias = matched_category_name)
            else:
                self.add_category_and_tags(category_name)
                field_name = self._category_field_name_map[category_name]
                if field_name not in existing_fields:
                    helper_functions.drop_add_field(poi_fc, field_name, "SHORT", field_alias = category_name)


    def reclassify_poi_all_to_new_category(self, poi_fc:Path,
                                                old_category_name:str,
                                                new_category_name:str,
                                                delete_old_field:bool=False,
                                                set_all_old_to_zero:bool=True):
        """Takes all the POI in the old category with a value of 1 and assigns a value of 1"""
        new_matched_category_name = self.get_match(new_category_name, self._category_tag_match)
        old_matched_category_name = self.get_match(old_category_name, self._category_tag_match)
        old_field_name = self._category_field_name_map[old_matched_category_name]

        if new_matched_category_name is None:
            self.add_category_and_tags(new_category_name)
        new_field_name = self._category_field_name_map[new_matched_category_name]
        self.add_categories_as_fields(poi_fc, new_matched_category_name)
        arcpy.management.CalculateField(str(poi_fc), new_field_name, "0", "PYTHON3")
        sel_layer = arcpy.management.SelectLayerByAttribute(str(poi_fc), "NEW_SELECTION", f"{old_field_name} = 1").getOutput(0)
        arcpy.management.CalculateField(sel_layer, new_field_name, "1", "PYTHON3")
        if delete_old_field is True and set_all_old_to_zero is False:
            arcpy.management.DeleteField(str(poi_fc), old_field_name)
        elif set_all_old_to_zero is True:
            arcpy.management.CalculateField(sel_layer, old_field_name, "0", "PYTHON3")

    def reclassify_poi_selection_to_new_category(self, poi_selected,
                                                old_category_name:str,
                                                new_category_name:str,
                                                set_all_old_to_zero:bool=True):
        
        """Takes the feature layer with a selection and assigns them to a new category"""
        new_matched_category_name = self.get_match(new_category_name, self._category_tag_match)
        old_matched_category_name = self.get_match(old_category_name, self._category_tag_match)
        old_field_name = self._category_field_name_map[old_matched_category_name]

        if new_matched_category_name is None:
            self.add_category_and_tags(new_category_name)
        new_field_name = self._category_field_name_map[new_matched_category_name]

        # Doing this here because poi_selected is an object and not the path
        existing_fields = [f.name for f in arcpy.ListFields(poi_selected)]
        if new_field_name not in existing_fields:
            arcpy.management.AddField(poi_selected, new_field_name, "SHORT", field_alias=new_matched_category_name)

        arcpy.management.CalculateField(poi_selected, new_field_name, "0", "PYTHON3")
        
        arcpy.management.CalculateField(poi_selected, new_field_name, "1", "PYTHON3")

        if set_all_old_to_zero is True:
            arcpy.management.CalculateField(poi_selected, old_field_name, "0", "PYTHON3")

        
    def check_exclusion(self, tags):
        """See if the tags are excluded"""
        for rule in self._exclusions:
            etag, evalue = rule['tag'], rule['val']
            if etag in tags:
                actual_val = tags[etag]
                if evalue == "*":
                    if rule.get('exception') == actual_val:
                        continue 
                    return True
                if actual_val == evalue:
                    return True
        return False


    def classify(self, tags):
        matched_cats = set()
        matched_classes = set()

        if self.check_exclusion(tags):
            return matched_cats, matched_classes

        for cat_name, rules in self._category_tag_match.items():
            if rules:
                for osm_k, expected_vals in rules.items():
                    if osm_k in tags:
                        if expected_vals is None:
                            matched_cats.add(cat_name)
                            matched_classes.add(osm_k)

                        elif tags[osm_k] in expected_vals:
                            matched_cats.add(cat_name)
                            matched_classes.add(tags[osm_k])
        
        return matched_cats, matched_classes