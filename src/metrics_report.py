from pathlib import Path
import json
import math
import arcpy
import pickle
import os

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.gridspec as gridspec
import matplotlib.image as mpimg
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import matplotlib.colors
import seaborn as sns

from typing import Literal
from datetime import datetime

import pandas as pd
import numpy as np
import yaml
from static_tools import helper_functions
from metrics_nodes_report import metric_full
from managers import settingsManager
import time
import textwrap

class generate_report(settingsManager):
    REPORT_CREATE_ACCESS_MAPS = True  # Access change category maps; CAUTION: long runtime
    REPORT_CREATE_POP_MAP = True # Population summary maps
    REMOVE_MAP_OBJECTS = False # Delete map objects after creation; adds to runtime
    REPORT_CREATE_PARALLEL_POICOUNT = True # Pre/post line charts of count of POIs accessible at each time threshold
    REPORT_CREATE_LOLLIPOP_CHART = True # Lollipop chart of average POI count reachable pre vs. post
    REPORT_CREATE_STACKED_BAR_CHART = True # Population count bar charts (decrease, no change, increase)
    REPORT_OVERALL_RATIO = True  # Cumulative POI pre vs. post access ratio by travel time

    def __init__(
        self, 
        projectFolder: Path, 
        scenarioName: str,
        metricsFolder: Path,
        metrics: list,
        scratchFolder:Path=None,
        metrics_type: Literal["cumulative", "dual"]="cumulative",
        metrics_weight: str = None
    ):

        super().__init__(projectFolder, scenario_name=scenarioName)

        self.metrics_folder = metricsFolder
        self.metrics = metrics
        self.metrics_type = metrics_type

        self.image_paths = []
        self.aprx_cleanup = []
        self.scratchFolder= scratchFolder
        self.orientation = "Portrait" #"Landscape" 

        if self.scratchFolder is None:
            self.scratchFolder = self.project_folder / self.scenario_name / self.metrics_folder
        
        if metrics_weight:
            self.metrics_weight = metrics_weight
        else:
            self.metrics_weight = self.schema_info["field_name_population"]

        self.metrics_df = self.load_metrics_outputs()
        self.metrics_df_wide = self.make_wide()

        self.modes = self.metrics_df["mode"].unique().tolist()
        self.poi_field_map = self.settings_info.get("poi_field_map", {})
        self.poi_types = self.metrics_df["poi_type"].unique().tolist()
        for poi_type in self.poi_types:
            if poi_type not in self.poi_field_map:
                self.poi_types.remove(poi_type)
                arcpy.AddWarning(f"POI type {poi_type} in metrics DataFrame not found in POI field map. Dropping from report.")

        self.process_date = datetime.now().strftime("%y%m%d%H%M")
        
        arcpy.AddMessage(f"Metric type: {self.metrics_type}.")

    def load_metrics_outputs(self):
        """
            Reads the metrics from the pickle file
            Args:
                None
            Returns:
                Concatenated outputs dataframe
        """
        arcpy.AddMessage(Path(f"{self.project_folder}/{self.scenario_name}/{self.metrics_folder}"))
        arcpy.AddMessage(f"{self.metrics_folder}")
        arcpy.AddMessage(f"{self.metrics}")
        output_dfs = []
        for output_file in self.metrics:
            metrics_path = f"{self.project_folder}/{self.scenario_name}/{self.metrics_folder}/{output_file}"
            with open(metrics_path, "rb") as f:
                output_df = pickle.load(f)
                output_dfs.append(output_df)
        return pd.concat(output_dfs, ignore_index=True)
    
    def create_report(self):
        """
            Creates compiled PDF report with Population Map, Overall Ratio, and Cumulative/Dual Parallel POI Count, Lollipop, Cumulative Bar Chart, 
            and maps for each POI category and threshold 
            Args:
                None
            Returns:
                None
        """
        arcpy.AddMessage("Creating report figures...")

        gdb_path = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb"
        for fc_base in [self.schema_info["fc_name_origin_nodes"], self.schema_info["fc_name_census_block_prj"]]:
            for prefix in ["metrics_", "buffered_"]:
                stale_fc = str(gdb_path / f"{prefix}{fc_base}")
                if arcpy.Exists(stale_fc):
                    arcpy.AddMessage(f"Clearing old origins layers: {prefix}{fc_base}")
                    try:
                        arcpy.management.Delete(stale_fc)
                    except Exception as e:
                        arcpy.AddWarning(f"Could not delete {stale_fc}. It may be open in ArcGIS Pro.")

        mode_to_name = {v:k for k,v in self.settings_info["mode_name_matching"].items()}
        # Generates a standardized pdfName in the format metrics_summary_yyyy_mm_dd_metrictype_mode1_mode2.pdf
        pdfName = f"report_{self.process_date}_{self.metrics_type[:4]}_{'_'.join(self.modes)}.pdf"
        # Generates the path where the metrics pdf is saved 
        pdfPath = self.project_folder/self.scenario_name/self.metrics_folder/ pdfName

        # Confirm the file is not open, if it is add a number for every iteration
        if pdfPath.exists() is True:
            index = 1
            while True:
                try:
                    # This will fail if another process has an exclusive lock
                    with open(pdfPath, 'r+') as f:
                        pass
                    break
                except PermissionError:
                    arcpy.AddMessage(f"Existing file {pdfName} in use.")
                    pdfName = f"report_{self.process_date}_{self.metrics_type[:4]}_{'_'.join(self.modes)}_{index}.pdf"
                    arcpy.AddMessage(f"New name: {pdfName}.")
                    pdfPath = self.project_folder/self.scenario_name/self.metrics_folder/ pdfName
                    if pdfPath.exists() is False:
                        break
                    index +=1
                except FileExistsError:
                    arcpy.AddError(f"FileExistsError file {pdfName}")
                    break
                except FileNotFoundError:
                    break
        # Creates page_width variable based on width in inches from the report_settings
        page_width = self.report_settings["report_settings"]["width_in"]
        # Creates page_height variable based on height in inches from the report_settings
        page_height = self.report_settings["report_settings"]["height_in"]
        # Creates figsize variable based on width and height variables
        figsize = (page_width, page_height)
        dpi = self.report_settings["report_settings"]["dpi"]

  
        with PdfPages(pdfPath) as pdf:
            self.create_cover_page(pdf)
            if self.REPORT_CREATE_POP_MAP:
                origins_fc = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / self.schema_info["fc_name_census_block_prj"]
                if not arcpy.Exists(str(origins_fc)):
                    map_configs = [(self.metrics_weight, f"Origin Distribution Map: {self.metrics_weight.replace('_', ' ').title()}")]
                    desc_prefix = "origin"
                else:
                    map_configs = [(self.metrics_weight, f"Census Block Distribution Map: {self.metrics_weight.replace('_', ' ').title()}")]
                    desc_prefix = "Census block"
                # Creates Origin Distribution Map (Census Block Population default) map
                for fld, lbl in map_configs:
                    success = False
                    image_outpath = self.project_folder/self.scenario_name/self.metrics_folder/f"census_blocks_{fld}.png"
                    success = self.map_population_household(image_outpath, field=fld, lbl=lbl)
                    if success is True:
                        img = mpimg.imread(image_outpath)
                        ax, _, description_box = self.create_figure(figsize, include_legend=False)
                        ax.tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
                        ax.ticklabel_format(useOffset=False, style="plain")
                        for d,s in ax.spines.items():
                            s.set_visible(False)
                        ax.imshow(img, aspect='auto')
                        desc_text = f"""{lbl} distribution by {desc_prefix} within the selected\nscenario area. Blocks with a weight of 0 are excluded from the analysis."""
                        description_box.text(.02, .5, desc_text, ha='left',va='center')
                        plt.tight_layout()
                        pdf.savefig()
                        
            if self.REPORT_OVERALL_RATIO:
                mf_obj = metric_full(self.project_folder, self.scenario_name, self.poi_types, self.modes)
                rows = len(self.modes)
                columns = 1
                axesDict = self.create_figure_with_panels(figsize, rows, columns)
                for ax in axesDict.values():
                    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f'))
                
                if len(self.poi_types) > 4:
                    poi_string = ', '.join(self.poi_types[0:4]) + '\n' + ', '.join(self.poi_types[4:])
                else:
                    poi_string = ', '.join(self.poi_types)
                descText = f"""Network Node Access Ratios: The relative number of travel network nodes accessible on the\nscenario network compared to the original network. The value is expressed as a ratio by travel\ntime along the x-axis, based on the cumulative count of travel network nodes accessible\nup to a given travel time. When the line is below 1 there was a decrease in access.\nTravel network nodes are filtered to include only nodes that facilitate\naccess to one or more points of interest in the following POI categories:\n{poi_string}"""
                mf_obj.create_overview_plot(axesDict, pdf, 60, descText)
                    
            if self.metrics_type == "cumulative":
                # Generates Parallel POI Count, Lollipop, and Bar Charts
                if self.REPORT_CREATE_PARALLEL_POICOUNT:
                    if arcpy.env.isCancelled:
                        # Raising an exception will break the script 
                        # immediately from wherever it is currently executing.
                        raise Exception("User Cancelled via ArcGIS UI")
                    self.summary_total_pois_by_threshold(pdf)

            if self.REPORT_CREATE_LOLLIPOP_CHART:
                if arcpy.env.isCancelled:
                    # Raising an exception will break the script 
                    # immediately from wherever it is currently executing.
                    raise Exception("User Cancelled via ArcGIS UI")
                self.summary_pre_post_change(pdf)
            
            if self.REPORT_CREATE_STACKED_BAR_CHART:
                if arcpy.env.isCancelled:
                    # Raising an exception will break the script 
                    # immediately from wherever it is currently executing.
                    raise Exception("User Cancelled via ArcGIS UI")
                self.plot_summary_info_counts(pdf)
                
            # Generates Ratio Maps for every mode, POI type, and threshold (when cumulative)
            if self.REPORT_CREATE_ACCESS_MAPS:
                threshold_type = self.metrics_type
                if threshold_type == "cumulative":
                    thresholds = [c[len("within_"):] for c in self.metrics_df.columns if isinstance(c, str) and c.startswith("within_")]
                elif threshold_type == "dual":
                    nth_dict = dict(zip(self.metrics_df["poi_type"], self.metrics_df["nth_destination"]))
                    thresholds = ["travel_time_sec"]
                layouts = []
                arcpy.AddMessage("Creating data for ratios.")
                for mode in self.modes:
                    for poi_type in self.poi_types:
                        for threshold in thresholds:
                            if arcpy.env.isCancelled:
                                # Raising an exception will break the script 
                                # immediately from wherever it is currently executing.
                                raise Exception("User Cancelled via ArcGIS UI")
                            self.create_ratio_data(mode, poi_type, threshold)
                arcpy.AddMessage("Creating map layouts.")
                for mode in self.modes:
                    for poi_type in self.poi_types:
                        for threshold in thresholds: 
                            if arcpy.env.isCancelled:
                                # Raising an exception will break the script 
                                # immediately from wherever it is currently executing.
                                raise Exception("User Cancelled via ArcGIS UI")       
                            # Create variable poi_type_clean from poi_type without unwanted character types
                            poi_type_clean = self.settings_info.get("poi_field_map", {})[poi_type]
                            image_outpath = self.project_folder/self.scenario_name/self.metrics_folder/f"{mode}_{poi_type_clean}_{threshold}_{threshold_type}.png"
                            #success = False
                            #try:
                            layout = self.map_ratio_for_mode_poi_pdf(
                                mode = mode,
                                poi_type = poi_type,
                                threshold = threshold,
                                image_outpath = image_outpath
                                )
                            if self.metrics_type == "cumulative":
                                layout_metadata = {
                                    "mode": mode_to_name[mode],
                                    "poi_type": poi_type,
                                    "threshold": str(threshold) + " minutes"
                                }
                            elif self.metrics_type == "dual":
                                layout_metadata = {
                                    "mode": mode_to_name[mode],
                                    "poi_type": poi_type,
                                    "nth_destination": str(int(nth_dict[poi_type]))
                                }
                            if layout is not None:
                                layouts.append((image_outpath, layout, layout_metadata))
                            #except:
                            #    arcpy.AddWarning(f"There was an error creating the map output for {mode}, {poi_type}, {threshold}.")
                arcpy.AddMessage("Exporting layouts.")
                for image_outpath, layout, layout_metadata in layouts:
                    arcpy.AddMessage(f"Exporting {image_outpath}")
                    layout.exportToPNG(str(image_outpath), resolution=dpi)
                    time.sleep(5)
                    img = mpimg.imread(image_outpath)
                    ax, _, description_box = self.create_figure(figsize, include_legend=False)
                    ax.tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
                    ax.ticklabel_format(useOffset=False, style="plain")
                    for d,s in ax.spines.items():
                        s.set_visible(False)
                    ax.imshow(img, aspect='auto')
                    if self.metrics_type == "cumulative":
                        desc_text = f"""Access Maps: The change in access to points of interest for the scenario\nnetwork compared to the original network. Change is computed based on the\nratio of POIs accessible on the scenario network vs. the original network\nfor the given POI category and time threshold.\nMode: {layout_metadata['mode']}; POI Category: {layout_metadata['poi_type']}; Threshold: {layout_metadata['threshold']}"""
                    elif self.metrics_type == "dual":
                        desc_text = f"""Access Maps: The change in access to points of interest for the scenario\nnetwork compared to the original network. Change is computed based on the\nratio of travel time to the Nth POI on the scenario network vs. the original network\nfor the given POI category.\nMode: {layout_metadata['mode']}; POI Category: {layout_metadata['poi_type']}; Nth Destination: {layout_metadata['nth_destination']}"""
                    description_box.text(.02, .5, desc_text, ha='left',va='center')
                    plt.tight_layout()
                    pdf.savefig()

        # Open the PDF report for the user
        os.startfile(str(pdfPath))

        if self.REMOVE_MAP_OBJECTS:
            arcpy.AddMessage("Cleaning up maps and layouts.")
            for r in self.aprx_cleanup:
                for obj in r["objects"]:
                    r["aprx"].deleteItem(obj)

        return
    
    def create_cover_page(self, pdf):
        """
        Creates a cover page with the local TrACKIT logo, report summary info, and OSM attribution.
        """
        import textwrap # Ensure this is imported at the top of your script
        
        arcpy.AddMessage("Creating cover page...")
        
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        figsize = (page_width, page_height)
        
        # Create a blank figure
        fig, ax = plt.subplots(figsize=figsize)
        ax.axis('off')
        
        # 1. Add Logo
        logo_path = self.file_path.parent / "TrACKIT_Logo_v1.png" 
        
        if logo_path.exists():
            try:
                img = mpimg.imread(logo_path)
                # Position the logo near the top center [left, bottom, width, height]
                ax_logo = fig.add_axes([0.35, 0.8, 0.3, 0.15]) 
                ax_logo.imshow(img)
                ax_logo.axis('off')
            except Exception as e:
                arcpy.AddWarning(f"Error loading local logo: {e}")
        else:
            arcpy.AddWarning(f"Could not find logo at {logo_path}. Skipping logo on cover page.")

        # 2. Add Title
        ax.text(0.5, 0.82, "Scenario Analysis", fontsize=30, fontweight='bold', ha='center', va='top', transform=ax.transAxes)

        # 3. Gather Summary Information
        run_time = datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')
        if self.metrics_type == "cumulative":
            threshold_cols = [c for c in self.metrics_df.columns if isinstance(c, str) and c.startswith("within_")]
            thresholds_text = ", ".join([c.replace("within_", "") for c in threshold_cols])
        
        # Define a helper to wrap bullet points with a hanging indent (6 spaces to clear "    • ")
        def wrap_bullet(text):
            return textwrap.fill(text, width=60, subsequent_indent="      ")

        included_reports = []
        if self.REPORT_CREATE_POP_MAP: 
            included_reports.append(wrap_bullet("Origin Distribution Maps"))
        if self.REPORT_OVERALL_RATIO: 
            included_reports.append(wrap_bullet("Network Node Access Ratios"))
            
        if self.metrics_type == "cumulative":
            if len(threshold_cols) > 1 and self.REPORT_CREATE_PARALLEL_POICOUNT: 
                included_reports.append(wrap_bullet("POI Access Change by Travel Time"))
            elif len(threshold_cols) == 1 and self.REPORT_CREATE_PARALLEL_POICOUNT:
                included_reports.append(wrap_bullet("POI Access Change by Travel Time skipped (only one threshold selected)"))
            
        if self.REPORT_CREATE_LOLLIPOP_CHART: 
            included_reports.append(wrap_bullet("Lollipop Chart"))
        if self.REPORT_CREATE_STACKED_BAR_CHART: 
            included_reports.append(wrap_bullet("Population Bar Chart"))
        if self.REPORT_CREATE_ACCESS_MAPS: 
            included_reports.append(wrap_bullet("Access Maps"))
        
        reports_str = "\n\n    • ".join([""] + included_reports)
        
        # Apply hanging indents to POI Types (11 spaces to clear "POI Types: ")
        if self.metrics_type == "cumulative":
            poi_types_string = ", ".join(self.poi_types)
        elif self.metrics_type == "dual":
            concat_poi = self.metrics_df["poi_type"] + ' (n=' + self.metrics_df["nth_destination"].astype(int).astype(str) + ')'
            poi_types_string = ", ".join(concat_poi.unique().tolist())
        poi_text = textwrap.fill(poi_types_string, width=70, subsequent_indent="           ")
        
        # Apply hanging indents to Modes (7 spaces to clear "Modes: ")
        mode_mapping = {v: k for k, v in self.settings_info.get("mode_name_matching", {}).items()}
        modes_concat = ", ".join([mode_mapping.get(m, m) for m in self.metrics_df["mode"].unique()])
        modes_text = textwrap.fill(modes_concat, width=70, subsequent_indent="       ")

        if self.metrics_type == "cumulative":
            summary_text = (
                f"Run Date/Time: {run_time}\n\n"
                f"Metric Type: {self.metrics_type.capitalize()}\n\n"
                f"Modes: {modes_text}\n\n"
                f"POI Types: {poi_text}\n\n"
                f"Thresholds (Minutes): {thresholds_text}\n\n"
                f"Included Reports:{reports_str}"
            )
        elif self.metrics_type == "dual":
            summary_text = (
                f"Run Date/Time: {run_time}\n\n"
                f"Metric Type: {self.metrics_type.capitalize()}\n\n"
                f"Modes: {modes_text}\n\n"
                f"POI Types: {poi_text}\n\n"
                f"Included Reports:{reports_str}"
            )
        
        # Add summary text to the middle of the page
        ax.text(0.02, 0.65, summary_text, fontsize=11, linespacing=1, ha='left', va='top', transform=ax.transAxes)

        # 4. Add OSM Attribution
        # Removed internal \n so textwrap can correctly reflow the paragraph
        osm_raw = (
            "OpenStreetMap® is open data, licensed under the Open Data Commons Open Database License (ODbL) by the OpenStreetMap Foundation (OSMF). "
            "You are free to copy, distribute, transmit and adapt our data, as long as you credit OpenStreetMap and its contributors. "
            "If you alter or build upon our data, you may distribute the result only under the same licence. "
            "The full legal code explains your rights and responsibilities."
        )
        
        osm_wrapped = textwrap.fill(osm_raw, width=100)
        osm_text = f"{osm_wrapped}\nhttps://www.openstreetmap.org/copyright"
        
        ax.text(0.5, 0.01, osm_text, fontsize=7, style='italic', color='dimgray', ha='center', va='bottom', transform=ax.transAxes)
        
        # Save the page to the PDF. Because this is the first thing added to the pdf object, it will be page 1.
        pdf.savefig(fig)
        plt.close(fig)


    def make_wide(self):
        """
            Creates merged dataframe (prenetwork and postnetwork) for origin_id, poi_type, mode, metrics_weight
            Args:
                None
            Returns:
                Merged dataframe
        """     
        # Creates two dataframes (prenetwork and postnetwork) from the "metrics_df" "network" column
        
        pre_val = self.schema_info["field_name_prenetwork"]
        post_val = self.schema_info["field_name_postnetwork"]

        prenetwork = self.metrics_df.query(f"network == '{pre_val}'").drop(columns=['network'])
        postnetwork = self.metrics_df.query(f"network == '{post_val}'").drop(columns=['network'])
        
        # Creates "base_keys" List variable with key column names
        if self.metrics_type == 'cumulative':
            base_keys = ['origin_id', 'poi_type', 'mode', self.metrics_weight]
        elif self.metrics_type == 'dual':
            base_keys = ['origin_id', 'poi_type', 'nth_destination', 'mode', self.metrics_weight]

        return pd.merge(prenetwork, postnetwork, on=base_keys, suffixes=('_pre', '_post'))

    def create_figure(self, figsize, include_legend=True):
        """
            Creates a formatted figure (figure height/width, column/row height/width), legend, and ticks)
            Args:
                figsize
                include_legend(bool)
            Returns:
                ax_plot, ax_plot_legend, ax_desc
        """
        fig = plt.figure(figsize=figsize)
        row_heights = [.9, .1]
        column_widths = [.9, .1]
        gs = gridspec.GridSpec(nrows=len(row_heights), ncols=len(column_widths), figure=fig, height_ratios=row_heights, width_ratios=column_widths)
        if include_legend:
            ax_plot = fig.add_subplot(gs[0,0])
            ax_plot_legend = fig.add_subplot(gs[0,1])
        else:
            ax_plot = fig.add_subplot(gs[0,0:2])
            ax_plot_legend = None

        ax_desc = fig.add_subplot(gs[1,0:2])
        ax_desc.tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
        ax_desc.ticklabel_format(useOffset=False, style="plain")
        ax_desc.set_frame_on(False)
        return ax_plot, ax_plot_legend, ax_desc

    def create_figure_with_panels(self, figsize, rows=1, columns=2, panels=None):
        """
            Creates a grid of figures with specified number of rows and columns and (optionally) panels
            Args:
                figsize
                rows
                columns
                panels
            Returns:
                axes
        """    
        fig = plt.figure(figsize=figsize)
        row_area = (1 - .2 - .1) / rows
        column_area = 1 / columns
        row_heights = [row_area for i in range(0, rows)] + [.2, .1]
        column_widths = [column_area for i in range(0, columns)]
        if panels is None:
            panels = rows * columns

        gs = gridspec.GridSpec(nrows=len(row_heights), ncols=len(column_widths), figure=fig, height_ratios=row_heights, width_ratios=column_widths)
        axes = {"axLeg":None, "axDesc":None}
        panels_made = 0
        for r in range(0, rows):
            for c in range(0, columns):
                if panels_made < panels:
                    axes[f"ax{r*columns+c+1}"] = fig.add_subplot(gs[r,c])
                    panels_made += 1
        axes["axLeg"] = fig.add_subplot(gs[-2, 0:3])
        axes["axDesc"] = fig.add_subplot(gs[-1, 0:3])
        axes["axDesc"].tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
        axes["axDesc"].ticklabel_format(useOffset=False, style="plain")
        axes["axDesc"].set_frame_on(False)
        return axes

    def summary_info_dual(self):

        return
    
    def categorize_ratio(self, s):
        """
            Categorizes a ratio based on input "s"
            Args:
                s
            Returns:
                NaN, "below_1", "equal_1", or "above_1" 
        """     
        if pd.isna(s):
            return np.nan
        elif s < 1:
            return 'below_1'
        elif np.isclose(s, 1):
            return 'equal_1'
        else:
            return 'above_1'

    def summary_total_pois_by_threshold(self, pdf):
        """
            This function creates a parallel coordinate plot of the total number of POIs by type, mode, and threshold.
            Args:
                pdf (pdfpages): pdf to write the figure to
            Returns:
                None
        """
        arcpy.AddMessage("Total POIs by Threshold")
        # Page information is stored in the colors.json document 
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        dpi = self.report_settings["report_settings"]["dpi"]
        pal = self.report_settings["network_type_colors"]
        
        thresholds = [c for c in self.metrics_df.columns if isinstance(c, str) and c.startswith("within_")]
        thresholds_tick_labels = [f"Within {c.split('_')[-1]}" for c in thresholds]
        mode_to_name = {v:k for k,v in self.settings_info["mode_name_matching"].items()}
        if len(self.poi_types) > 12:
            ncols = 4
            nrows = len(self.poi_types) // 4 + 1
        elif len(self.poi_types) > 8:
            ncols = 3
            nrows = len(self.poi_types) // 3 + 1
        elif len(self.poi_types) > 1:
            ncols = 2
            nrows = len(self.poi_types) // 2 + 1
        else:
            ncols = 1
            nrows = 1
        
        if len(thresholds) > 1:
            for mode in self.metrics_df["mode"].unique():
                arcpy.AddMessage(f"Mode: {mode_to_name[mode]}")
                # Weight each census block "count" by the population, sum everything and divide by total population
                # Create a new column of count * population, calculate the total population as another variable, then do the group by on the weighted column
                df_counts = self.metrics_df.copy()
                pre_val = self.schema_info["field_name_prenetwork"]
                post_val = self.schema_info["field_name_postnetwork"]
                total_population = df_counts.loc[(df_counts["mode"] == mode)&(df_counts["network"]==pre_val)&(df_counts["poi_type"]==df_counts["poi_type"].iloc[0]), self.metrics_weight].sum()
                for threshold in thresholds:
                    # Overwrite threshold counts with weighted by population versions, only in temp df_counts DataFrame
                    df_counts[threshold] = df_counts[threshold] * df_counts[self.metrics_weight]
                axes = self.create_figure_with_panels((page_width, page_height), nrows, ncols, len(self.poi_types))
                for index, poi_type in enumerate(self.poi_types):
                    # Calculate weighted by population values for each POI type graph
                    df_counts_by_poi = df_counts[(df_counts["mode"] == mode)&(df_counts["poi_type"] == poi_type)].groupby("network")[thresholds].sum() / total_population
                    
                    # Renaming for legend clarity
                    df_counts_by_poi = df_counts_by_poi.rename(index={pre_val: "Original Network", post_val: "Scenario Network"})
                    
                    # Reindex ensures the "Original" row is first, which Seaborn uses to determine legend order
                    new_order = ["Original Network", "Scenario Network"]
                    df_counts_by_poi = df_counts_by_poi.reindex(new_order) 
                    
                    # Create local limits for subplot
                    local_max = df_counts_by_poi.values.max()
                    local_min = df_counts_by_poi.values.min()
                    # Add a small buffer (10% of the range)
                    y_range = local_max - local_min
                    # If all values are the same, range is 0; provide a default buffer
                    buffer = (y_range * 0.1) if y_range > 0 else 0.1
                    y_limit_min = max(0, math.floor(local_min - buffer))
                    y_limit_max = math.ceil(local_max + buffer)
            
                    # Create 3 standardized ticks for this specific range
                    standard_ticks = np.linspace(y_limit_min, y_limit_max, 3)
                    
                    # Plot lines
                    sns.lineplot(data=df_counts_by_poi.transpose(),
                                 palette=pal,
                                 dashes = {"Original Network": "", "Scenario Network": (2, 2)},
                                 ax=axes[f"ax{index+1}"], 
                                 linewidth=2)
                    axes[f"ax{index+1}"].get_legend().remove()
                    
                    # Format axes
                    axes[f"ax{index+1}"].set_xticklabels(thresholds_tick_labels, rotation=45)
                    axes[f"ax{index+1}"].set_ylim([y_limit_min, y_limit_max])
                    axes[f"ax{index+1}"].set_yticks(standard_ticks)
                    axes[f"ax{index+1}"].yaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f'))
                    axes[f"ax{index+1}"].vlines(thresholds, y_limit_min, y_limit_max, colors="k", alpha=.5, linewidth=1)
                    axes[f"ax{index+1}"].set_title(poi_type, fontsize=10)

                handles, labels = axes["ax1"].get_legend_handles_labels()
                axes["axLeg"].legend(handles, labels, title="Network Type", ncol=3, loc='upper center')
                axes["axLeg"].set_axis_off()
                   
                desc_text = f"""POI Access Change by Travel Time: The number of points of interest accessible\nto the average resident at each travel time threshold, POI type, and mode on\nthe Original Network vs. Scenario Network.\nMode: {mode_to_name[mode]}"""
                axes["axDesc"].text(.02, .5, desc_text, ha='left',va='center')

                plt.tight_layout()
                pdf.savefig()
        else:
            arcpy.AddMessage("Only one threshold has been selected. Skipping creation of parallel coordinate plots by threshold.")
            
    def summary_pre_post_change(self,pdf):
        """
            This function creates a "cleveland dotplot" or "lollipop" chart of the pre and post total number of POIs (for cumulative)
            or pre and post travel times to destination (for dual) by POI type, mode, and threshold (for cumulative).
            Args:
                pdf (pdfpages): pdf to write the figure to.
            Returns:
                None
        """
        if self.metrics_type == "cumulative":
            arcpy.AddMessage("Total POIs from Original Network to Scenario Network by Threshold and Mode")
        elif self.metrics_type == "dual":
            arcpy.AddMessage("Change in Travel Time to Nth Destination between Original Network and Scenario Network by Threshold and Mode")
        
        # Page information is stored in the colors.json document
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        dpi = self.report_settings["report_settings"]["dpi"]
        
        raw_colors = self.report_settings.get("colors_for_categories", [])
        base_colors = list(raw_colors.values()) if isinstance(raw_colors, dict) else list(raw_colors)
        base_poi_labels = self.settings_info.get("abbrevs_for_categories", {})
        pal = {pt: base_colors[i] if i < len(base_colors) else "#808080" for i, pt in enumerate(self.poi_types)}
        poi_labels = {pt: base_poi_labels.get(pt, pt[:3].upper()) for pt in self.poi_types}
        label_to_poi = {v:k for k,v in poi_labels.items()}

        mode_to_name = {v:k for k,v in self.settings_info["mode_name_matching"].items()}
        
        # Create a List variable with the thresholds
        # Create a List variable with the number of threshold values
        if self.metrics_type == "cumulative":
            thresholds = [c for c in self.metrics_df_wide.columns if isinstance(c, str) and c.startswith("within_")]
            threshold_values = [int(c.strip("within_")) for c in self.metrics_df.columns if isinstance(c, str) and c.startswith("within_")]
            threshold_values_prefix = "within_"
        elif self.metrics_type == "dual":
            thresholds = ["travel_time_sec_pre", "travel_time_sec_post"]
            threshold_values = ["travel_time_sec"]
            threshold_values_prefix = ""
            nth_dict = dict(zip(self.metrics_df["poi_type"], self.metrics_df["nth_destination"]))
        
        for mode in self.metrics_df["mode"].unique():
            arcpy.AddMessage(f"Mode: {mode_to_name[mode]}")
            # Creates dataframe with pre- and postnetwork POI counts for selected mode, grouped by poi_type
            df_counts_wide = self.metrics_df_wide.copy()
            total_population = df_counts_wide.loc[(df_counts_wide["mode"] == mode)&(df_counts_wide["poi_type"]==df_counts_wide["poi_type"].iloc[0]), self.metrics_weight].sum()
            for threshold in thresholds:
                # Overwrite threshold counts with weighted by population versions, only in temp df_counts_wide DataFrame
                df_counts_wide[threshold] = df_counts_wide[threshold] * df_counts_wide[self.metrics_weight]
            df_counts = df_counts_wide[(df_counts_wide["mode"] == mode)].groupby("poi_type")[thresholds].sum() / total_population
            df_counts = df_counts.reset_index()
            df_counts["y"] = np.arange(len(df_counts))
            
            if self.metrics_type == "dual":
                df_counts["travel_time_sec_pre"] = df_counts["travel_time_sec_pre"] / 60.0
                df_counts["travel_time_sec_post"] = df_counts["travel_time_sec_post"] / 60.0

            # Subtract _pre columns from the _pre and _post columns in df_counts before feeding into the graph
            # NOTE: For dual, negative values (to the left of the 0-axis) are good and positive values (to the right of the 0-axis) are bad
            for t in threshold_values:
                df_counts[f"{threshold_values_prefix}{t}_post"] = df_counts[f"{threshold_values_prefix}{t}_post"] - df_counts[f"{threshold_values_prefix}{t}_pre"]
                df_counts[f"{threshold_values_prefix}{t}_pre"] = 0
            
            # Create a graphic with panels, one for each mode. The number of rows and columns are variable with number of thresholds. 
            row_count = int(math.ceil(len(threshold_values)/2))
            col_count = 2 if len(threshold_values) > 1 else 1
            axes = self.create_figure_with_panels((page_width, page_height), rows=row_count, columns=col_count, panels=len(threshold_values))
        
            # Create horizontal lines from the pre to post values for each poi_type
            counter = 1 
            for t in threshold_values:
                for i, row in df_counts.iterrows():
                    axes[f"ax{counter}"].hlines(y=row['y'], xmin=min(row[f"{threshold_values_prefix}{t}_pre"], row[f"{threshold_values_prefix}{t}_post"]), xmax=max(row[f"{threshold_values_prefix}{t}_pre"], row[f"{threshold_values_prefix}{t}_post"]), color=pal[row["poi_type"]], label=poi_labels[row["poi_type"]], linewidth=2, zorder=1)
                    axes[f"ax{counter}"].scatter(row[f"{threshold_values_prefix}{t}_post"], row["y"], color=pal[row["poi_type"]], marker=".", edgecolors="none", s=160, zorder=3)
                counter += 1
                        
            handles, labels = axes["ax1"].get_legend_handles_labels()
            if self.metrics_type == "cumulative":
                full_labels = [f"{label_to_poi.get(label, label)} ({label})" for label in labels]
            elif self.metrics_type == "dual":
                full_labels = [f"{label_to_poi.get(label, label)} ({label}, N={str(int(nth_dict.get(label_to_poi.get(label, label), 1)))})" for label in labels]
            axes["axLeg"].legend(handles, full_labels, title="POI Type", ncol=3, loc='upper center')
            axes["axLeg"].set_axis_off()
            
            counter = 1
            for t in threshold_values:
                if self.metrics_type == "cumulative":
                    axes[f"ax{counter}"].set_title(f"{t} Minutes", fontsize=10)
                    axes[f"ax{counter}"].set_xlabel("Difference in Average POI Count Reachable")
                elif self.metrics_type == "dual":
                    axes[f"ax{counter}"].set_title(f"Difference in Travel Time (min)", fontsize=10)
                    axes[f"ax{counter}"].set_xlabel("Difference in Travel Time to Nth Destination")
                axes[f"ax{counter}"].tick_params(axis='y')
                axes[f"ax{counter}"].set_yticks(df_counts["y"], labels)
                # Create local limits for subplot
                local_max = df_counts[f"{threshold_values_prefix}{t}_post"].max()
                local_min = df_counts[f"{threshold_values_prefix}{t}_post"].min()
                # Add a small buffer (10% of the range)
                x_range = local_max - local_min
                # If all values are the same, range is 0; provide a default buffer
                buffer = (x_range * 0.1) if x_range > 0 else 0.1
                x_limit_min = min(-0.1, local_min - buffer)
                x_limit_max = max(0.1, local_max + buffer)
                axes[f"ax{counter}"].xaxis.set_major_locator(mticker.MaxNLocator(nbins='auto', steps=[1, 2, 5, 10]))
                # axes[f"ax{counter}"].xaxis.set_major_formatter(mticker.FormatStrFormatter('%.1f'))
                # xticks = np.arange(0, max_val, 2)
                # xlabels = [int(round(x, 1)) for x in xticks]
                # axes[f"ax{counter}"].set_xticks(xticks, labels = xlabels)
                axes[f"ax{counter}"].set_xlim(x_limit_min, x_limit_max)
                axes[f"ax{counter}"].axvline(x=0, color='black', linewidth=0.5)
                counter += 1
                
            if self.metrics_type == "cumulative":
                desc_text = f"""Lollipop Chart: Average change in the number of points of interest accessible\nto the average resident in each POI category for each travel time threshold.\nHorizontal lines show the average magnitude of change from the original network\nto the scenario network. Lines to the right of the 0-axis represent an average\nincrease in access; lines to the left of the 0-axis represent an average\ndecrease in access.\nMode: {mode_to_name[mode]}"""
            elif self.metrics_type == "dual":
                desc_text = f"""Lollipop Chart: Average change in travel time to the Nth destination\nfor the average resident in each POI category. Horizontal lines show the average magnitude\nof change from the original network to the scenario network.\nLines to the right of the 0-axis represent an average increase in travel time (decrease in access);\nlines to the left of the 0-axis represent an average decrease in travel time (increase in access).\nMode: {mode_to_name[mode]}"""
            axes["axDesc"].text(.02, .5, desc_text, ha='left',va='center')

            plt.tight_layout()
            pdf.savefig()
       
    def plot_summary_info_counts(self, pdf:PdfPages):
        """
            This function creates a report with stacked bar charts that represent the change in access (Increase, No Change, Decrease) to POI categories pre- and post-network.
            The function creates a separate graph for each threshold for each mode.  
            Args:
                pdf (pdfpages): pdf to write the figure to.
            Returns:
                None
        """
        
        if self.metrics_type == "cumulative":
            df = self.summary_info_counts_cumulative()
        elif self.metrics_type == "dual":
            df = self.summary_info_counts_dual()

        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        dpi = self.report_settings["report_settings"]["dpi"]
        mode_to_name = {v:k for k,v in self.settings_info["mode_name_matching"].items()}

        # Create category label column
        df["category_lbl"] = np.where(df["category"]=="equal_1", "No Change", "Increased")
        df["category_lbl"] = np.where(df["category"]=="below_1", "Decreased", df["category_lbl"])

        if self.metrics_type == "cumulative":
            # example of value in thresholds is "within_5"
            thresholds = [c for c in df["threshold"].unique() if isinstance(c, str) and c.startswith("within_")]
            # example of value in thresholds_tick_labels is "Within 5"
            thresholds_tick_labels = [f"Within {c.split('_')[-1]}" for c in thresholds]
        elif self.metrics_type == "dual":
            thresholds = ["travel_time_sec"]
            thresholds_tick_labels = ["Travel Time (sec)"]
            nth_dict = dict(zip(self.metrics_df["poi_type"], self.metrics_df["nth_destination"]))

        bar_height = 0.33
        
        # Colors
        if self.metrics_type == "cumulative":
            color_increase = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_cumulative_rgba"]["Significant Increase in Access"])
            color_no_change = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_cumulative_rgba"]["No Change in Access"])
            color_decrease = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_cumulative_rgba"]["Significant Decrease in Access"])
        elif self.metrics_type == "dual":
            color_increase = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_dual_rgba"]["Significant Increase in Travel Time"])
            color_no_change = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_dual_rgba"]["No Change in Travel Time"])
            color_decrease = tuple(v/255.0 for v in self.report_settings["colors_for_access_groups_dual_rgba"]["Significant Decrease in Travel Time"])
        
        color_increase = matplotlib.colors.to_hex(color_increase)
        color_no_change = matplotlib.colors.to_hex(color_no_change)
        color_decrease = matplotlib.colors.to_hex(color_decrease)

        patch_group1 = mpatches.Patch(color=color_increase, label='Increase')
        patch_group2 = mpatches.Patch(color=color_decrease, label='Decrease')
        patch_group3 = mpatches.Patch(color=color_no_change, label='No Change')

        # Loop through each mode and threshold
        for mode in df["mode"].unique():
            for threshold, titleTxt in zip(thresholds, thresholds_tick_labels):
                axes = self.create_figure_with_panels((page_width, page_height), 1, 1)
                ax = axes["ax1"]
                
                # Storage
                inc_vals, same_vals, dec_vals = [], [], []
                raw_inc, raw_same, raw_dec = [], [], []
                
                # Compute values per POI category
                for poitype in self.poi_types:
                    cdf = df[(df["mode"] == mode) & (df["threshold"] == threshold) & (df["poi_type"]==poitype)]

                    val_inc = float(cdf[cdf["category_lbl"]=="Increased"]["total_weights"].sum())
                    val_same = float(cdf[cdf["category_lbl"]=="No Change"]["total_weights"].sum())
                    val_dec = float(cdf[cdf["category_lbl"]=="Decreased"]["total_weights"].sum())

                    raw_inc.append(val_inc)
                    raw_same.append(val_same)
                    raw_dec.append(val_dec)

                    total = val_inc + val_same + val_dec
                    total = total if total > 0 else 1
                       
                    # Convert to percentages  
                    inc_vals.append(100 * val_inc  / total)
                    same_vals.append(100 * val_same / total)
                    dec_vals.append(100 * val_dec  / total)

                # Plot 100% stacked bars with different colors for cumulative and dual
                y_positions = np.arange(len(self.poi_types))
                ax.barh(y_positions, inc_vals, height = bar_height, color=color_increase)
                ax.barh(y_positions, same_vals, height = bar_height, left=inc_vals, color=color_no_change)
                ax.barh(y_positions, dec_vals, height = bar_height, left=np.array(inc_vals) + np.array(same_vals),color=color_decrease)

                # Add raw population labels
                vertical_offset = 0 if len(y_positions) == 1 else 0.25
                for i, y in enumerate(y_positions):
                    left_inc = 0
                    right_dec = inc_vals[i] + same_vals[i] + dec_vals[i]
                    left_offset = 2
                    right_offset = 16
                    
                     # Increase
                    inc_label = f"Increase: {int(round(raw_inc[i])):,}"
                    ax.text(left_inc + left_offset, y - vertical_offset, inc_label, fontsize=7)
                                   
                    # Decrease
                    dec_label = f"Decrease: {int(round(raw_dec[i])):,}"
                    ax.text(right_dec - right_offset, y - vertical_offset, dec_label, fontsize=7)
                    
                # Axes formatting
                ax.set_xlim([0, 100])
                ax.set_xlabel("Percent of Population")
                ax.set_ylabel("POI Category")
                ax.set_yticks(y_positions)
                
                if self.metrics_type == "cumulative":
                    ax.set_yticklabels([p.replace(" ","\n") for p in self.poi_types], fontsize=8)
                    ax.set_title(f"Population Bar Chart: Change in Access,\nDestinations {titleTxt} Minutes ({mode})", fontsize=14, pad = 20)
                elif self.metrics_type == "dual":
                    ax.set_yticklabels([p.replace(" ","\n") + "\n" + "N=" + str(int(nth_dict[p])) for p in self.poi_types], fontsize=8)
                    ax.set_title(f"Population Bar Chart: Change in Access,\nTravel Time to Nth Destination ({mode})", fontsize=14, pad = 20)
                ax.text(0.5, .97, f"Total Population: {int(round(total)):,}", transform=ax.transAxes, ha="center", fontsize=7)

                # Legend panel
                axes["axLeg"].legend(handles=[patch_group1, patch_group3, patch_group2], title="Access to POI" if self.metrics_type == "cumulative" else "Travel Time to Destination", ncol=3, loc='upper center')
                axes["axLeg"].set_axis_off()

                if self.metrics_type == "cumulative":
                    desc_text = f"""Population Bar Chart: Share of population impacted by changes in\naccess to POI categories in the scenario network compared to the\noriginal network. Shown as 100% stacked bars with labels showing\npopulation counts of residents expected to see an increase, decrease,\nor no change in access to POIs of different types.\nMode: {mode_to_name[mode]}; Threshold: {threshold}"""
                elif self.metrics_type == "dual":
                    desc_text = f"""Population Bar Chart: Share of population impacted by changes in\naccess to POI categories in the scenario network compared to the\noriginal network. Shown as 100% stacked bars with labels showing\npopulation counts of residents expected to see an increase, decrease,\nor no change in travel time to the Nth destination.\nMode: {mode_to_name[mode]}"""
                axes["axDesc"].text(.02, .5, desc_text, ha='left', va='center')

                plt.tight_layout()
                pdf.savefig(bbox_inches='tight', pad_inches=0.05)
                plt.close()

        pass
    
    def summary_info_counts_cumulative(self):
        """
            Creates a dataframe with ratios used in plot_summary_info_counts method for cumulative df
            Args:
                None
            Returns:
                result
        """      
        pre_cols = [c for c in self.metrics_df_wide.columns if c.endswith('_pre')]
        thresholds = [c[:-4] for c in pre_cols]  # strip '_pre' suffix

        df = self.metrics_df_wide.copy()

        rows = []

        for t in thresholds:
            pre_col = t + '_pre'
            post_col = t + '_post'
            ratio_col = t + '_post_div_pre'
            # Compute ratio columns if missing
            if ratio_col not in df.columns:
                pre_vals = pd.to_numeric(df[pre_col], errors='coerce').fillna(0).astype(float)
                post_vals = pd.to_numeric(df[post_col], errors='coerce').fillna(0).astype(float)
                with np.errstate(divide='ignore', invalid='ignore'):
                    ratio = post_vals / pre_vals
                    ratio = np.where(
                        pre_vals == 0,
                        np.where(post_vals == 0, 1.0, np.inf),
                        ratio
                    )
                df[ratio_col] = ratio

            # Apply category per ratio column, avoid modifying entire df multiple times by working on a Series
            categories = df[ratio_col].apply(self.categorize_ratio)

            # Instead groupby on a column, so assign temporary category column
            df_temp = df.copy()
            df_temp['category'] = categories

            grp = df_temp.groupby(['mode', 'poi_type', 'category'])

            summary = grp.agg(
                count_geoid=('origin_id', 'count'),
                total_weights=(self.metrics_weight, 'sum')
            ).reset_index()

            summary['threshold'] = t  

            rows.append(summary)

        result = pd.concat(rows, ignore_index=True)

        # reorder columns
        cols = ['mode', 'poi_type', 'threshold', 'category', 'count_geoid', 'total_weights']
        result = result[cols]
        return result

    def summary_info_counts_dual(self):
        """
            Creates a dataframe with ratios used in plot_summary_info_counts method for dual df
            Args:
                None
            Returns:
                result
        """      
        df = self.metrics_df_wide.copy()

        pre_col = 'travel_time_sec_pre'
        post_col = 'travel_time_sec_post'
        ratio_col = 'travel_time_sec_post_div_pre'
        # Compute ratio columns if missing
        # A value of NaN for dual means the nth destination is inaccessible
        if ratio_col not in df.columns:
            pre_vals = pd.to_numeric(df[pre_col], errors='coerce').astype(float)
            post_vals = pd.to_numeric(df[post_col], errors='coerce').astype(float)
            with np.errstate(divide='ignore', invalid='ignore'):
                ratio = post_vals / pre_vals
                
                ratio = np.where(
                    (pd.isnull(pre_vals) & pd.isnull(post_vals)) | ((pre_vals == 0) & (post_vals == 0)), 1.0, ratio)
                
                #Improved access for dual needs to be closer to 0 (shorter travel time is better).
                ratio = np.where(
                    pd.isnull(pre_vals) & pd.notnull(post_vals), 0, ratio)

                #Decreased access for dual needs to be greater than 0 (longer travel time is worse)
                ratio = np.where(
                    pd.isnull(post_vals) & pd.notnull(pre_vals), np.inf, ratio)
            df[ratio_col] = ratio

        # Apply category per ratio column, avoid modifying entire df multiple times by working on a Series
        categories = df[ratio_col].apply(self.categorize_ratio)

        # Instead groupby on a column, so assign temporary category column
        df_temp = df.copy()
        df_temp['category'] = categories

        grp = df_temp.groupby(['mode', 'poi_type', 'nth_destination', 'category'])

        result = grp.agg(
            count_geoid=('origin_id', 'count'),
            total_weights=(self.metrics_weight, 'sum')
        ).reset_index()
        result['threshold'] = "travel_time_sec"

        # reorder columns
        cols = ['mode', 'poi_type', 'nth_destination', 'threshold', 'category', 'count_geoid', 'total_weights']
        result = result[cols]
        return result

    # NOTE: Not currently used anywhere
    def summary_info_average_cumulative(self, keep_infinite:bool=False):
        """
            Calculates summary metrics by census block, mode, POI type, threshold
            Summary metrics are: 'mean_ratio', 'median_ratio', 'std_ratio', 'n_valid',
                'n_inf', self.metrics_weight
            Args:
                keep_infinite (bool)
            Returns:
                agg
        """       
        # identify pre cols and thresholds
        pre_cols = [c for c in self.metrics_df_wide.columns if c.endswith('_pre')]
        thresholds = [c[:-4] for c in pre_cols]  # e.g. 'within_30'
        df = self.metrics_df_wide.copy()

        for t in thresholds:
            pre_col = f"{t}_pre"
            post_col = f"{t}_post"
            ratio_col = f"{t}_post_div_pre"
            # calculate ratio column if does not exist
            if ratio_col not in df.columns:
                pre_vals = pd.to_numeric(df[pre_col], errors='coerce').fillna(0).astype(float)
                post_vals = pd.to_numeric(df[post_col], errors='coerce').fillna(0).astype(float)
                with np.errstate(divide='ignore', invalid='ignore'):
                    ratio = post_vals / pre_vals
                    ratio = np.where(
                        pre_vals == 0,
                        np.where(post_vals == 0, 1.0, 100.0),
                        ratio
                    )
                df[ratio_col] = ratio

        # list ratio cols
        ratio_cols = [f"{t}_post_div_pre" for t in thresholds]

        # Optionally treat infinities as NaN for aggregation (we'll still count them separately)
        tmp = df.copy()
        # inf_mask is True where original was inf/-inf
        inf_mask = tmp[ratio_cols].replace([np.inf, -np.inf], np.nan).isna() & tmp[ratio_cols].notna()

        if not keep_infinite:
            tmp[ratio_cols] = tmp[ratio_cols].replace([np.inf, -np.inf], np.nan)

        # Melt to long form
        melt_df = tmp.melt(
            id_vars=['origin_id', 'mode', 'poi_type', self.metrics_weight],
            value_vars=ratio_cols,
            var_name='ratio_col',
            value_name='ratio'
        )

        # extract threshold name from ratio_col (strip suffix)
        melt_df['threshold'] = melt_df['ratio_col'].str.replace(r'_post_div_pre$', '', regex=True)

        # count inf occurrences per row (from inf_mask) - rebuild a long inf indicator
        # construct a DataFrame for inf flags in long form
        inf_flags = inf_mask.reset_index().melt(
            id_vars=['index'],
            value_vars=ratio_cols,
            var_name='ratio_col',
            value_name='is_inf'
        )
        # align index with melt_df rows
        inf_flags = inf_flags.sort_values(['index', 'ratio_col']).reset_index(drop=True)
        melt_df = melt_df.sort_values(['origin_id', 'mode', 'poi_type', 'ratio_col']).reset_index(drop=True)
        # If shapes align, append is_inf; safer approach: create a multiindex map
        # create a key for matching: original row index + ratio_col
        # to do that, use original df index as id in melt
        df_with_idx = tmp.reset_index().rename(columns={'index': '_orig_index'})
        melt_df = df_with_idx.melt(
            id_vars=['_orig_index', 'origin_id', 'mode', 'poi_type', self.metrics_weight],
            value_vars=ratio_cols,
            var_name='ratio_col',
            value_name='ratio'
        )
        melt_df['threshold'] = melt_df['ratio_col'].str.replace(r'_post_div_pre$', '', regex=True)

        # Build an is_inf column from the original (before replacement) df
        orig_inf = df.reset_index().rename(columns={'index': '_orig_index'})
        orig_inf_long = orig_inf.melt(
            id_vars=['_orig_index'],
            value_vars=ratio_cols,
            var_name='ratio_col',
            value_name='orig_ratio'
        )
        orig_inf_long['is_inf'] = orig_inf_long['orig_ratio'].isin([np.inf, -np.inf])
        # merge is_inf into melt_df
        melt_df = melt_df.merge(orig_inf_long[['_orig_index', 'ratio_col', 'is_inf']],
                                on=['_orig_index', 'ratio_col'], how='left')

        # Now group by origin/mode/poi_type/threshold
        group_cols = ['origin_id', 'mode', 'poi_type', 'threshold']
        grp = melt_df.groupby(group_cols, dropna=False)

        agg = grp['ratio'].agg(
            mean_ratio='mean',
            median_ratio='median',
            std_ratio='std',
            n_valid=lambda s: s.count()  # counts non-NA values
        ).reset_index()

        # count infinities per group (from is_inf flag)
        n_inf = grp['is_inf'].sum().reset_index().rename(columns={'is_inf': 'n_inf'})

        # Get origin metric weight (take first non-null)
        pop_hu = melt_df.groupby(['origin_id', 'mode', 'poi_type'], as_index=False).agg({
            self.metrics_weight: 'first'
        })

        # Merge origin metrics weight into agg (join on origin/mode/poi_type)
        agg = agg.merge(pop_hu, on=['origin_id', 'mode', 'poi_type'], how='left')
        agg = agg.merge(n_inf, on=group_cols, how='left')

        # If keep_infinite==False, we already excluded inf from ratio; if True, n_inf still counts infinities
        agg['n_inf'] = agg['n_inf'].fillna(0).astype(int)

        # Reorder columns
        cols = ['origin_id', 'mode', 'poi_type', 'threshold',
                'mean_ratio', 'median_ratio', 'std_ratio', 'n_valid', 'n_inf',
                self.metrics_weight]
        agg = agg[cols]

        return agg

    # NOTE: Not currently used anywhere
    def weighted_average_by_group(self, df_origin_threshold):
        """
        Given a DataFrame like the output of summary_info_average_cumulative(),
        compute population-weighted average of mean_ratio grouped by mode, poi_type, threshold.
        Parameters:
            df_origin_threshold (pd.DataFrame): output from summary_info_average_cumulative()
        Returns:
            pd.DataFrame with columns: ['mode', 'poi_type', 'threshold', 'weighted_mean_ratio', 'total_population']
        """
        # Filter out rows with zero or missing population to avoid division errors
        df = df_origin_threshold.dropna(subset=[self.metrics_weight]).copy()
        df = df[df[self.metrics_weight] > 0]

        # Calculate weighted sum of mean_ratio times population
        df['weighted_sum'] = df['mean_ratio'] * df[self.metrics_weight]

        # Group by mode, poi_type, threshold to compute weighted averages and sum population
        grouped = df.groupby(['mode', 'poi_type', 'threshold'], as_index=False).agg(
            weighted_sum_pop=('weighted_sum', 'sum'),
            total_population=(self.metrics_weight, 'sum')
        )

        # Compute weighted average
        grouped['weighted_mean_ratio'] = grouped['weighted_sum_pop'] / grouped['total_population']

        # Clean up
        result = grouped.drop(columns='weighted_sum_pop')

        return result

    def map_population_household(self, image_outpath:Path, map_project_path:Path=None, field:str="POP100", lbl:str=""):
        """
            This function creates a map and layout that shows the user specified origin weights (default total population of the census blocks) and saves to a png
            Args:
                image_outpath (Path): path to the png file for the output
                map_project_path (Path): path to the ArcGIS Pro project, if none the current project is used
                field (str): field name in the "fc_name_census_block_prj" feature class to be mapped
                lbl (str): name used in the layer name
            Returns:
                True if completed
        """
        scenario_gdb = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb"
        scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
        scen_name_fld = self.schema_info["field_name_scenario_name"]
        orig_type_fld = self.schema_info["field_name_origin_type"]
        
        # Default to points just in case
        origin_type_val = "Custom Points" 
        
        # Read the actual origin type used for this scenario
        with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, orig_type_fld]) as cursor:
            for row in cursor:
                if row[0] == self.scenario_name:
                    if row[1]:
                        origin_type_val = str(row[1])
                    break

        fc_census = scenario_gdb / self.schema_info["fc_name_census_block_prj"]
        fc_poly = scenario_gdb / self.schema_info["fc_name_custom_origin_polygons"]
        fc_nodes = scenario_gdb / self.schema_info["fc_name_origin_nodes"]

        # Route to the correct feature class based on the origin type string
        if "Census Blocks" in origin_type_val:
            origins_fc_path = fc_census
        elif "Custom Polygons" in origin_type_val:
            origins_fc_path = fc_poly
        else:
            origins_fc_path = fc_nodes

        map_fc_path = str(origins_fc_path)
        desc = arcpy.Describe(map_fc_path)
        if desc.shapeType == "Point":
            buffered_fc = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / f"buffered_{origins_fc_path.name}"
            
            if not arcpy.Exists(str(buffered_fc)):
                # Dynamic buffer distance based on scenario radius
                scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
                scen_name_fld = self.schema_info["field_name_scenario_name"]
                radius_fld = self.schema_info["field_name_scenario_buffer"] 
                
                scenario_radius_mi = 10.0 
                
                with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, radius_fld]) as cursor:
                    for row in cursor:
                        if row[0] == self.scenario_name:
                            if row[1]: 
                                scenario_radius_mi = float(row[1])
                            break

                proportion = 0.03
                buffer_dist = scenario_radius_mi * proportion * 5280
                buffer_string = f"{buffer_dist} Feet"
                
                arcpy.analysis.Buffer(map_fc_path, str(buffered_fc), buffer_string)
                
            map_fc_path = str(buffered_fc)
        
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        dpi = self.report_settings["report_settings"]["dpi"]
                
        if map_project_path is None or map_project_path.exists() is False:
            map_project_path = "CURRENT"

        aprx = arcpy.mp.ArcGISProject(str(map_project_path))
        m = self.create_map(aprx, "census", self.metrics_weight, "data")

        clean_name = lbl.split(': ')[-1]
        layer_name = f"Total {clean_name}"
        
        make_lyr = arcpy.management.MakeFeatureLayer(map_fc_path, layer_name).getOutput(0)


        layer = m.addLayer(make_lyr, "TOP")[0]
        layer.transparency = 20

        sym = layer.symbology
        # Only proceed if layer supports symbology as a graduated renderer (feature layers)
        #try:
        sym.updateRenderer('GraduatedColorsRenderer')
        sym.renderer.classificationField = field
        sym.renderer.classificationMethod = "Quantile"
        sym.renderer.breakCount = 5
        sym.renderer.colorRamp = aprx.listColorRamps('Yellow-Green-Blue (5 Classes)')[0]
        layer.symbology = sym
        l_cim = layer.getDefinition('V3')
        prev_bound = 0
        for i, brk in enumerate(l_cim.renderer.breaks):
            if prev_bound == 0:
                brk.label = f"<= {brk.upperBound:,}"
                
            else:
                brk.label = f"{prev_bound:,} - {brk.upperBound:,}"
            prev_bound = brk.upperBound
        layer.setDefinition(l_cim)

        changes_layer = self.add_project_changes_layer(m)
        if changes_layer is not None:
            for cl in changes_layer:
                cl.transparency = 35

        layout, mf_ratio = self.create_layout(aprx, layer, m, "census", self.metrics_weight, "data", page_width, page_height)
        
        # create Array of Points
        leg_coords = [[0.3, .3], [page_width * .3, 0.3], [page_width * .3, page_height * .3],
              [0.6, page_height * .3]]
        leg_pt_array = arcpy.Array([arcpy.Point(x, y) for x, y in leg_coords])

        if leg_coords[0] != leg_coords[-1]:
            leg_coords.append(leg_coords[0])

        # create polygon (geometry object)
        leg_polygon = arcpy.Polygon(leg_pt_array)

        # style item
        style_path = str(self.file_path / "TrACKIT_Legend.stylx")
        
        current_styles = aprx.styles
        if style_path not in current_styles:
            current_styles.append(style_path)
            aprx.updateStyles(current_styles)
        arcpy.AddMessage(f"Active styles ({lbl}): {';'.join(aprx.styles)}")
        legSi = aprx.listStyleItems(style_path, 'LEGEND', 'TrACKIT Legend')[0]

        # create legend surround using a Polygon geometry (not an Array)
        leg = layout.createMapSurroundElement(leg_polygon, 'LEGEND', mf_ratio, legSi, 'Legend')
        legDefinition = leg.getDefinition('V3')
        leg.fittingStrategy = 'ManualColumns'
        leg.columnCount = 1

        for item in legDefinition.items:
            item.showHeading = False
            lns = item.layerNameSymbol
            lns.symbol.height = 10
        
            if item.name in ["Updated", "Removed", "New"]:
                item.showLayerName = False
        
        leg.setDefinition(legDefinition)

        try:
            arcpy.RefreshActiveView()
            arcpy.RefreshTOC()
        except Exception:
            # Refresh may not be available in some contexts; ignore safely
            pass
        # small pause to let rendering complete; tune as needed (0.5-1.5s)
        
        arcpy.RefreshLayer(layer)
        if changes_layer is not None:
            for cl in changes_layer:
                arcpy.RefreshLayer(cl)
        
        time.sleep(0.75)

        layout.exportToPNG(str(image_outpath), resolution=dpi)

        self.aprx_cleanup.append({"aprx":aprx, "objects":[layout, m]})

        return True

    def create_ratio_data(self, mode, poi_type, threshold, geoid_field: str = None, out_field_name:str=None):
        scenario_gdb = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb"
        scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
        scen_name_fld = self.schema_info["field_name_scenario_name"]
        orig_type_fld = self.schema_info["field_name_origin_type"]
        
        origin_type_val = "Custom Points" 
        with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, orig_type_fld]) as cursor:
            for row in cursor:
                if row[0] == self.scenario_name:
                    if row[1]: origin_type_val = str(row[1])
                    break

        fc_census = scenario_gdb / self.schema_info["fc_name_census_block_prj"]
        fc_poly = scenario_gdb / self.schema_info["fc_name_custom_origin_polygons"]
        fc_nodes = scenario_gdb / self.schema_info["fc_name_origin_nodes"]

        if "Census Blocks" in origin_type_val:
            origins_fc_path = fc_census
        elif "Custom Polygons" in origin_type_val:
            origins_fc_path = fc_poly
        else:
            origins_fc_path = fc_nodes
            
        if geoid_field is None:
            geoid_field = self.schema_info["field_name_origin_id"]

        pois_fc_path = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / self.schema_info["fc_name_scenario_pois_nodes"]
        if arcpy.Exists(str(origins_fc_path)) is False:
            raise Exception("Missing origin nodes for the given scenario")
        
        origins_fc_path_metrics = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / f'metrics_{origins_fc_path.name}'

        if arcpy.Exists(str(origins_fc_path_metrics)) is False:
            arcpy.AddMessage("Creating origin Feature Class for mapping.")
            desc = arcpy.Describe(str(origins_fc_path))
            if desc.shapeType == "Point":
                arcpy.AddMessage("Origins are points. Buffering to create polygons for the access map.")
                
                # Dynamic buffer distance based on scenario radius
                scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
                scen_name_fld = self.schema_info["field_name_scenario_name"]
                radius_fld = self.schema_info["field_name_scenario_buffer"] 
                
                # Default to 1 mile just in case the table lookup fails
                scenario_radius_mi = 10.0 
                
                with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, radius_fld]) as cursor:
                    for row in cursor:
                        if row[0] == self.scenario_name:
                            # Catch cases where the radius might be empty/None
                            if row[1]: 
                                scenario_radius_mi = float(row[1])
                            break
                
                # Set your proportion here (e.g., 0.10 = 10% of the scenario radius)
                proportion = 0.03
                buffer_dist = scenario_radius_mi * proportion * 5280
                buffer_string = f"{buffer_dist} Feet"
                
                arcpy.AddMessage(f"Using a buffer distance of {buffer_string} for point origins in the maps.")
                
                arcpy.analysis.Buffer(str(origins_fc_path), str(origins_fc_path_metrics), buffer_string)
                # -----------------------------------------
                
            else:
                arcpy.CopyFeatures_management(str(origins_fc_path), str(origins_fc_path_metrics))

        # 1) ensure ratio exists in metrics_df_wide
        ratio_col = f"{threshold}_post_div_pre"
        if ratio_col not in self.metrics_df_wide.columns:
            if self.metrics_type == "cumulative":
                pre_col = f"within_{threshold}_pre"
                post_col = f"within_{threshold}_post"
            elif self.metrics_type == "dual":
                pre_col = f"{threshold}_pre"
                post_col = f"{threshold}_post"
            if pre_col not in self.metrics_df_wide.columns or post_col not in self.metrics_df_wide.columns:
                raise KeyError(f"Missing required columns: {pre_col} and/or {post_col}")
            pre_vals_raw = pd.to_numeric(self.metrics_df_wide[pre_col], errors='coerce').astype(float)
            post_vals_raw = pd.to_numeric(self.metrics_df_wide[post_col], errors='coerce').astype(float)
            with np.errstate(divide='ignore', invalid='ignore'):
                if self.metrics_type == "cumulative":
                    pre_vals = pre_vals_raw.fillna(0)
                    post_vals = post_vals_raw.fillna(0)
                    ratio = post_vals / pre_vals
                    ratio = np.where(pre_vals == 0, np.where(post_vals == 0, 1.0, np.inf), ratio)
                elif self.metrics_type == "dual":
                    pre_vals = pre_vals_raw
                    post_vals = post_vals_raw
                    ratio = post_vals / pre_vals
                    ratio = np.where((pd.isnull(pre_vals) & pd.isnull(post_vals)) | ((pre_vals == 0) & (post_vals == 0)), 1.0, ratio)
                    ratio = np.where(pd.isnull(pre_vals) & pd.notnull(post_vals), 0.0, ratio)
                    ratio = np.where(pd.isnull(post_vals) & pd.notnull(pre_vals), np.inf, ratio)
            self.metrics_df_wide[ratio_col] = ratio

        # 2) filter rows for mode & poi_type and build mapping origin_id -> ratio
        df = self.metrics_df_wide.copy()
        df_filtered = df[(df['mode'] == mode) & (df['poi_type'] == poi_type)].copy()
        if df_filtered.empty:
            raise ValueError(f"No rows found for mode='{mode}' and poi_type='{poi_type}'")

        if 'origin_id' not in df_filtered.columns:
            raise KeyError("metrics_df_wide must have 'origin_id' column")

        ratio_map = dict(zip(df_filtered['origin_id'].astype(str), df_filtered[ratio_col].astype(float)))

        # 3) prepare field name
        if out_field_name is None:
            poi_clean = self.settings_info.get("poi_field_map", {})[poi_type]
            out_field_name = f"ratio_{mode}_{poi_clean}_{threshold}"
        
        helper_functions.drop_add_field(origins_fc_path_metrics, out_field_name, "DOUBLE")
        arcpy.AddMessage(out_field_name)
            
        # 4) populate field
        count_updated = 0
        count_null = 0
        with arcpy.da.UpdateCursor(str(origins_fc_path_metrics), [geoid_field, out_field_name]) as ucur:
            for row in ucur:
                if row[0] is not None:
                    #if "GEOID" not in row[0]:
                    #    geoid_val = f"GEOID_{row[0]}"
                    #else:
                    geoid_val = row[0]
                    if geoid_val in ratio_map:
                        val = ratio_map[geoid_val]
                        # Handle inf/nan: write None for NaN, write a large number for inf or leave None - prefer None
                        if val is None or (isinstance(val, float) and np.isnan(val)):
                            row[1] = None
                            count_null += 1
                        elif np.isinf(val):
                            # Write large sentinel so it falls in correct symbology band
                            row[1] = 999.0
                            count_updated += 1
                        else:
                            row[1] = float(val)
                            count_updated += 1
                    else:
                        row[1] = None
                        count_null += 1
                else:
                    row[1] = None
                    count_null += 1
                ucur.updateRow(row)

        arcpy.AddMessage(f"Updated {count_updated} features; {count_null} left NULL")

    def add_project_changes_layer(self, m):
        changes_fc_path = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / "scenario_project_changes"
        
        if not arcpy.Exists(str(changes_fc_path)):
            return None

        action_field = self.schema_info.get("field_name_action", "action")
        action_colors = self.report_settings.get("action_colors", {})
        created_layers = []
        
        schema_actions = [a.lower() for a in self.schema_info.get("action_options", [])]
        draw_order = [a for a in ["removed", "updated", "new"] if a in schema_actions]

        for i, action_lower in enumerate(draw_order):
            action = next((a for a in self.schema_info["action_options"] if a.lower() == action_lower), action_lower.title())
            
            layer_name = action.title()
                
            # Create a unique internal name so ArcPy doesn't silently add " 1", " 2", etc.
            mem_name = f"mem_{layer_name}_{m.name}"
            
            make_lyr = arcpy.management.MakeFeatureLayer(str(changes_fc_path), mem_name, f"{action_field} = '{action}'").getOutput(0)
            
            if int(arcpy.management.GetCount(make_lyr).getOutput(0)) == 0:
                arcpy.management.Delete(make_lyr)
                continue

            # 20% Transparency applied here
            layer = m.addLayer(make_lyr, "TOP")[0]
            layer.transparency = 20
            layer.name = layer_name 
            
            rgb = action_colors.get(action, [0, 0, 0, 255])
            color_vals = rgb if len(rgb) == 4 else rgb + [255]
            
            cim_lyr = layer.getDefinition('V3')
            cim_lyr.renderer = {
                "type": "CIMSimpleRenderer",
                "label": action.title(),
                "symbol": {
                    "type": "CIMSymbolReference",
                    "symbol": {
                        "type": "CIMLineSymbol",
                        "symbolLayers": [{
                            "type": "CIMSolidStroke",
                            "width": 3.25,
                            "color": {"type": "CIMRGBColor", "values": color_vals}
                        }]
                    }
                }
            }
            layer.setDefinition(cim_lyr)
            created_layers.append(layer)
            
        if created_layers:
            created_layers[-1].name = "Scenario Changes"
            
        return created_layers if created_layers else None

    def map_ratio_for_mode_poi_pdf(
        self,
        mode: str,
        poi_type: str,
        threshold: str,
        image_outpath: Path,
        geoid_field: str = None,
        out_field_name: str = None,
        map_project_path: Path = None
    ):
        """
        Create a map for mode & poi_type & threshold, symbolize the ratio field, and export to PDF.
        Args:
            mode, poi_type, threshold: filters and threshold to select and create ratio column (e.g., "within_30" for cumulative, "travel_time_sec" for dual)
            pdf_outpath: full path to output PDF file
            origins_fc_path: path to connectors_nodes feature class
            geoid_field: field name in connectors FC that matches origin_id in metrics_df_wide
            out_field_name: optional desired field name in connectors to store the ratio (auto if None)
            map_project_path: optional .aprx file to use; if None the CURRENT project is used (must be run inside Pro)
        Returns:
            path to exported PDF
        """
        scenario_gdb = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb"
        scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
        scen_name_fld = self.schema_info["field_name_scenario_name"]
        orig_type_fld = self.schema_info["field_name_origin_type"]
        
        origin_type_val = "Custom Points" 
        with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, orig_type_fld]) as cursor:
            for row in cursor:
                if row[0] == self.scenario_name:
                    if row[1]: origin_type_val = str(row[1])
                    break

        fc_census = scenario_gdb / self.schema_info["fc_name_census_block_prj"]
        fc_poly = scenario_gdb / self.schema_info["fc_name_custom_origin_polygons"]
        fc_nodes = scenario_gdb / self.schema_info["fc_name_origin_nodes"]

        if "Census Blocks" in origin_type_val:
            origins_fc_path = fc_census
        elif "Custom Polygons" in origin_type_val:
            origins_fc_path = fc_poly
        else:
            origins_fc_path = fc_nodes
            
        if geoid_field is None:
            geoid_field = self.schema_info["field_name_origin_id"]

        # Point the map directly to the metrics layer (which already has the buffer and the data!)
        origins_fc_path_metrics = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / f'metrics_{origins_fc_path.name}'
        map_fc_path = str(origins_fc_path_metrics)

        pois_fc_path = self.project_folder / self.scenario_name / f"{self.scenario_name}.gdb" / self.schema_info["fc_name_scenario_pois_nodes"]
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        field_names = [f.name for f in arcpy.ListFields(origins_fc_path_metrics)]

        if out_field_name is None:
            poi_clean = self.settings_info.get("poi_field_map", {})[poi_type]
            out_field_name = f"ratio_{mode}_{poi_clean}_{threshold}"
        
        if out_field_name not in field_names:
            arcpy.AddWarning(f"Data may not be available for this threshold {threshold} and mode {mode}")
            return None
        
        if map_project_path is None or map_project_path.exists() is False:
            map_project_path = "CURRENT"
        
        # 5) Open aprx and add layer and render (ArcGIS Pro)
        aprx = arcpy.mp.ArcGISProject(str(map_project_path))
        aprx.closeViews("LAYOUTS")
        m = self.create_map(aprx, mode, poi_type, threshold)

        mode_mapping = {v: k for k, v in self.settings_info.get("mode_name_matching", {}).items()}
        mode_clean = mode_mapping.get(mode, mode.replace('_', ' ').title())

        if self.metrics_type == "cumulative":
            layer_name = f"Ratio for {poi_type} by {mode_clean} ({threshold} min)"
        elif self.metrics_type == "dual":
            layer_name = f"Ratio for {poi_type} by {mode_clean} ({threshold})"
        make_lyr = arcpy.management.MakeFeatureLayer(map_fc_path, layer_name).getOutput(0)
        layer = m.addLayer(make_lyr, "TOP")[0]
        layer.transparency = 25
        layer.name = f"Access Ratio ({mode_clean}, {poi_type}, {threshold})"

        sym = layer.symbology
        # Only proceed if layer supports symbology as a graduated renderer (feature layers)
        sym.updateRenderer('GraduatedColorsRenderer')
        sym.renderer.classificationField = out_field_name
        sym.renderer.breakCount = 5
        layer.symbology = sym
        # set break values
        if self.metrics_type == "cumulative":
            labels = [k for k in self.report_settings["colors_for_access_groups_cumulative_rgba"].keys()]
            colors = [self.report_settings["colors_for_access_groups_cumulative_rgba"][x] for x in labels]
        elif self.metrics_type == "dual":
            labels = [k for k in self.report_settings["colors_for_access_groups_dual_rgba"].keys()]
            colors = [self.report_settings["colors_for_access_groups_dual_rgba"][x] for x in labels]
        layerDefinition = layer.getDefinition('V3')
        
        layerDefinition.renderer.breaks = [
            {
                "upperBound": 0.965,
                "label": labels[0],
                "symbol": {"type": "CIMSymbolReference", "symbol": {"type": "CIMPolygonSymbol", "symbolLayers": [{"type":"CIMSolidFill","color":colors[0]}]}}
            },
            {
                "upperBound": 0.99,
                "label": labels[1],
                "symbol": {"type": "CIMSymbolReference", "symbol": {"type": "CIMPolygonSymbol", "symbolLayers": [{"type":"CIMSolidFill","color":colors[1]}]}}
            },
            {
                "upperBound": 1.01,
                "label": labels[2],
                "symbol": {"type": "CIMSymbolReference", "symbol": {"type": "CIMPolygonSymbol", "symbolLayers": [{"type":"CIMSolidFill","color":colors[2]}]}}
            },
            {
                "upperBound": 1.035,
                "label": labels[3],
                "symbol": {"type": "CIMSymbolReference", "symbol": {"type": "CIMPolygonSymbol", "symbolLayers": [{"type":"CIMSolidFill","color":colors[3]}]}}
            },
            {
                "upperBound": 1e12,  
                "label": labels[4],
                "symbol": {"type": "CIMSymbolReference", "symbol": {"type": "CIMPolygonSymbol", "symbolLayers": [{"type":"CIMSolidFill","color":colors[4]}]}}
            }
        ]

        layer.setDefinition(layerDefinition)

        fieldName = self.settings_info.get("poi_field_map", {})[poi_type]
        dq = f"{fieldName.lower()} = 1"
        make_lyr = arcpy.management.MakeFeatureLayer(str(pois_fc_path), f"{poi_type}", where_clause=dq).getOutput(0)
        pois_layer = m.addLayer(make_lyr, "TOP")[0]
        pois_layer.transparency = 1
        pois_layer.name = f"{poi_type} POIs"

        pois_symbology = pois_layer.symbology

        pois_symbology.renderer.symbol.applySymbolFromGallery("Circle 1")
        
        rgba = [150, 150, 150, 130] # medium gray, slightly transparent
        if hasattr(pois_symbology, 'renderer'):
            #symbology.updateRenderer("SimpleRenderer")
            renderer = pois_symbology.renderer
            renderer.symbol.color = {"RGB":rgba} 
            renderer.symbol.outlineColor = {"RGB": [100, 100, 100, 180]}
            renderer.symbol.size = 3
            renderer.symbol.angle = 0
            renderer.symbol.outlineWidth = 0.5
        pois_layer.symbology = pois_symbology

        changes_layer = self.add_project_changes_layer(m)
        layout, mf_ratio = self.create_layout(aprx, layer, m, mode, poi_type, threshold, page_width, page_height)
        
        # create Array of Points
        leg_coords = [[0.3, .3], [page_width * .3, 0.3], [page_width * .3, page_height * .3],
              [0.6, page_height * .3]]
        leg_pt_array = arcpy.Array([arcpy.Point(x, y) for x, y in leg_coords])

        if leg_coords[0] != leg_coords[-1]:
            leg_coords.append(leg_coords[0])

        # create polygon (geometry object)
        leg_polygon = arcpy.Polygon(leg_pt_array)

        # style item
        style_path = str(self.file_path / "TrACKIT_Legend.stylx")
        current_styles = aprx.styles
        if style_path not in current_styles:
            current_styles.append(style_path)
            aprx.updateStyles(current_styles)
        arcpy.AddMessage(f"Active styles ({mode} | {poi_type}): {';'.join(aprx.styles)}")
        legSi = aprx.listStyleItems(style_path, 'LEGEND', 'TrACKIT Legend')[0]

        # create legend surround using a Polygon geometry (not an Array)
        leg = layout.createMapSurroundElement(leg_polygon, 'LEGEND', mf_ratio, legSi, 'Legend')
        legDefinition = leg.getDefinition('V3')
        leg.fittingStrategy = 'ManualColumns'
        leg.columnCount = 1

        for item in legDefinition.items:
            item.showHeading = False
            lns = item.layerNameSymbol
            lns.symbol.height = 10
            
            if item.name in ["Updated", "Removed", "New"]:
                item.showLayerName = False
        
        leg.setDefinition(legDefinition)

        layout.openView()
        arcpy.RefreshLayer(layer)
        arcpy.RefreshLayer(pois_layer)
        if changes_layer is not None:
            for cl in changes_layer:
                arcpy.RefreshLayer(cl)
        time.sleep(10)
        try:
            arcpy.RefreshActiveView()
            arcpy.RefreshTOC()
        except Exception:
            # Refresh may not be available in some contexts; ignore safely
            pass
        # small pause to let rendering complete; tune as needed (0.5-1.5s)
        #time.sleep(2)

        #layout.exportToPNG(str(image_outpath), resolution=dpi)

        self.aprx_cleanup.append({"aprx":aprx, "objects":[layout, m]})

        return layout
        
    def create_map(self, proj, mode, poi_type, threshold):
        """
        Basic function to create a map with the given args and selected basemap
        Args:
            proj, mode, poi_type, threshold
        Returns:
           map "m"
        """
        m = proj.createMap(f"Map_ratio_{mode}_{poi_type}_{threshold}")
        try:
            # Common basemap names: 'Topographic', 'Streets', 'Streets (Vector)',
            # 'Imagery', 'Imagery (Clarity)', 'Light Gray Canvas', 'Dark Gray Canvas',
            # 'Oceans', 'National Geographic', 'OpenStreetMap'
            m.addBasemap('Light Gray Canvas')   # choose one
            arcpy.AddMessage(f"Set basemap to: Light Gray Canvas")
        except Exception as e:
            arcpy.AddWarning(f"Could not set basemap via m.basemap: {e}")
        return m
    
    def create_layout(self, proj, layer, m, mode, poi_type, threshold, page_width, page_height):
        """
        Basic function to create an ArcGIS layout with the given args 
        Args:
            proj, layer, m(map), mode, poi_type, threshold, page_width, page_height
        Returns:
           layout and mf_ratio (MapFrame Ratio)
        """
        layout = None
        layout_name = f"layout_ratio_{mode}_{poi_type}_{threshold}"
        layout = proj.createLayout(page_width, page_height, "INCH", layout_name)
        
        mf_coords = [[0.2, 0.2], [page_width - 0.2, 0.2], [page_width - 0.2, page_height - 0.8], [0.2, page_height - 0.8], [0.2, 0.2]]
        mf_rect = arcpy.Array([arcpy.Point(*coords) for coords in mf_coords])
        mf_ratio = layout.createMapFrame(arcpy.Polygon(mf_rect), m, f'mf_ratio_{mode}_{poi_type}_{threshold}')

        # Define and add the dynamic title banner
        title_coords = [[0.2, page_height - 0.7], [page_width - 0.2, page_height - 0.7], [page_width - 0.2, page_height - 0.2], [0.2, page_height - 0.2], [0.2, page_height - 0.7]]
        title_poly = arcpy.Polygon(arcpy.Array([arcpy.Point(*coords) for coords in title_coords]))
        
        poi_clean = poi_type.replace('_', ' ').title()
        poi_clean = poi_clean[:-1] if poi_clean.endswith('s') else poi_clean

        if mode == "census":
            title_text = f"Origin Weight Distribution Map: {poi_type.replace('_', ' ').title()}"
        else:
            mode_mapping = {v: k for k, v in self.settings_info.get("mode_name_matching", {}).items()}
            mode_clean = mode_mapping.get(mode, mode.replace('_', ' ').title())
            
            if self.metrics_type == "cumulative":
                title_text = f'Cumulative Access Ratio Map: Number of "{poi_clean}" Destinations in {threshold} Min, {mode_clean} Mode'
            else:
                # Fetch the exact Nth destination value for this POI type
                nth_val = 1
                if "nth_destination" in self.metrics_df.columns:
                    matches = self.metrics_df[self.metrics_df["poi_type"] == poi_type]["nth_destination"]
                    if not matches.empty:
                        nth_val = int(matches.iloc[0])
                
                # Determine suffix (st, nd, rd, th)
                suffix = "th"
                if nth_val % 10 == 1 and nth_val % 100 != 11: suffix = "st"
                elif nth_val % 10 == 2 and nth_val % 100 != 12: suffix = "nd"
                elif nth_val % 10 == 3 and nth_val % 100 != 13: suffix = "rd"
                
                title_text = f'Dual Access Ratio Map: Travel Time to {nth_val}{suffix} "{poi_clean}" Destination, {mode_clean} Mode'

        title_elem = proj.createTextElement(
            container=layout, 
            geometry=title_poly, 
            text_type="POLYGON", 
            text=title_text, 
            text_size=14, 
            font_style_name="Bold", 
            name="DescriptiveMapTitle"
        )
        
        # Apply Center alignment using the CIM definition
        title_cim = title_elem.getDefinition('V3')
        if hasattr(title_cim, 'graphic'):
            title_cim.graphic.symbol.symbol.horizontalAlignment = "Center"
            title_elem.setDefinition(title_cim)

        # 1. Get the bounding box of your data layer
        ext = mf_ratio.getLayerExtent(layer)
        
        scenario_table = self.project_fgdb / self.schema_info["fc_scenario_table"]
        scen_name_fld = self.schema_info["field_name_scenario_name"]
        radius_fld = self.schema_info["field_name_scenario_buffer"] 
        
        scenario_radius_mi = 10.0 # Default fallback
        with arcpy.da.SearchCursor(str(scenario_table), [scen_name_fld, radius_fld]) as cursor:
            for row in cursor:
                if row[0] == self.scenario_name:
                    if row[1]: 
                        scenario_radius_mi = float(row[1])
                    break
        
        # Check map units to handle both Metric (UTM) and Imperial (State Plane) projections
        units_per_mile = 1609.34 if "Meter" in ext.spatialReference.linearUnitName else 5280.0
        
        # Set the minimum width to 1x the scenario radius (adjust the multiplier if you want it wider/tighter)
        min_width = scenario_radius_mi * units_per_mile * 0.15
        
        ext_width = ext.XMax - ext.XMin
        ext_height = ext.YMax - ext.YMin
        
        # If the extent is smaller than our minimum, artificially expand it from the center
        if ext_width < min_width or ext_height < min_width:
            center_x = (ext.XMax + ext.XMin) / 2
            center_y = (ext.YMax + ext.YMin) / 2
            
            # Create a square extent based on our minimum width
            half_width = min_width / 2
            ext.XMin = center_x - half_width
            ext.XMax = center_x + half_width
            ext.YMin = center_y - half_width
            ext.YMax = center_y + half_width
            
            # Recalculate height for the shift logic below
            ext_height = ext.YMax - ext.YMin
  
      
        x_padding = ext_width * 0.10          # 10% padding on the left and right
        y_padding_top = ext_height * 0.10     # 10% padding on the top so it doesn't get cut off
        y_padding_bottom = ext_height * 0.25  # 25% padding on the bottom to make room for the legend

        #Create the new, larger bounding box
        new_ext = arcpy.Extent(
            ext.XMin - x_padding,
            ext.YMin - y_padding_bottom,
            ext.XMax + x_padding,
            ext.YMax + y_padding_top,
            spatial_reference=ext.spatialReference
        )
                               
        # 5. Tell the camera to fit this new expanded box perfectly into the frame
        mf_ratio.camera.setExtent(new_ext)
        
        # (We no longer need to manually mess with mf_ratio.camera.scale because 
        # setExtent on our padded box automatically handles the zooming!)
        
        return layout, mf_ratio


### CODE FOR DEBUGGING OUTSIDE OF ARCGIS TOOLBOX ###
#go = generate_report(projectFolder= Path(r'E:\working\CoPDemo\CoP_TrACKIT_Demo\Centroids_project'), 
#                    scenarioName= 'Centroid_Scenario', 
#                    metricsFolder="Centroid_Scenario_cumulative_20251015_131155",
#                    metrics = ['Centroid_Scenario_bike_cumulative_metrics.metrics'])
#go.metrics_df.to_csv(r"C:\TrACKIT Workspace\Data\boston_full_area_project\boston_full_area_project\allston_project\allston_project_cumulative_20250908_155738\full_data.csv",index=False, encoding='utf-8-sig')
#go.metrics_df.to_pickle(r"C:\TrACKIT Workspace\Data\boston_full_area_project\boston_full_area_project\allston_project\allston_project_cumulative_20250908_155738\full_data.metrics")
#go.metrics_summary.to_csv(r"C:\TrACKIT Workspace\Data\boston_full_area_project\boston_full_area_project\allston_project\allston_project_cumulative_20250908_155738\grpd_ratio_counts.csv",
 #                          index=False, encoding='utf-8-sig')
#go.metrics_summary_avg.to_csv(r"C:\TrACKIT Workspace\Data\boston_full_area_project\boston_full_area_project\allston_project\allston_project_cumulative_20250908_155738\ratio_all.csv",
 #                          index=False, encoding='utf-8-sig')
#go.metrics_summary_avg_weighted.to_csv(r"C:\TrACKIT Workspace\Data\boston_full_area_project\boston_full_area_project\allston_project\allston_project_cumulative_20250908_155738\weighted_avg_ratio.csv",
 #                          index=False, encoding='utf-8-sig')
#pdf_path = Path(r"C:\Users\J.Blackwell-Lipkind\Downloads\ratio_map_walk_9_19.pdf")
#go.map_ratio_for_mode_poi_pdf(mode="walk", poi_type="Retail", threshold="within_15", pdf_outpath=pdf_path)
