from pathlib import Path
import arcpy

import json
import yaml
import os
import time
from datetime import datetime


import numpy as np
import pandas as pd
from arcgis.features import GeoAccessor, GeoSeriesAccessor

from scipy.spatial import KDTree

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import seaborn as sns
import os
from managers import settingsManager
from managers import POICategoryManager


class match_nodes(settingsManager):
    def __init__(self, projectFolder:Path, scenario_name:str, poi_distance:float):
        super().__init__(projectFolder, scenario_name)

        self.scenario_folder = self.project_folder / self.scenario_name
        self.scenario_fgdb = self.scenario_folder / f"{self.scenario_name}.gdb"

        self.poi_data = self.scenario_fgdb / self.schema_info["fc_name_scenario_pois_nodes"]
        self.node_data = self.scenario_fgdb / self.schema_info["fc_name_integrated_nodes"]

        self.poi_distance = poi_distance

        self.categories_field_name = {'':'missing'}
        self.field_name_categories = {'missing':'missing'}
        self.df = None
        self.process_date = datetime.now().strftime('%Y_%m_%d')
        

        self.pcm = POICategoryManager(self.project_folder, self.project_fgdb)
        if len(self.settings_info["scenario_categories"]) > 0:
            self.field_name_categories = {f:label for label, f in self.pcm.get_category_fields().items() if label in self.settings_info["scenario_categories"]}
            self.categories_field_name = self.pcm.get_category_fields()

    def poimatch(self):
        #wc = "category not in ('', 'Origins')"
        arcpy.AddMessage(f"Matching POIs started at {datetime.now().strftime('%H:%M:%S')}")


        binary_fields = list(self.field_name_categories.keys())
        

        exploded_osmid = []
        exploded_types = []
        exploded_coords = []

        actual_fields = [f.name for f in arcpy.ListFields(str(self.poi_data))]
        missing_fields = [f for f in binary_fields if f not in actual_fields]
        binary_fields = [f for f in binary_fields if f in actual_fields]

        fields_to_read = [self.schema_info["field_name_poi_finalid"], "SHAPE@XY"] + binary_fields

        with arcpy.da.SearchCursor(str(self.poi_data), fields_to_read) as sc:
            for row in sc:
                osmid = row[0]
                xy = row[1]
                if xy is None:
                    continue

                category_values = row[2:]
                if all((v is None or int(v) ==0) for v in category_values):
                    continue

                for i, field_name in enumerate(binary_fields, start =2 ):
                    val = row[i]
                    try:
                        is_one = val is not None and int(val) != 0
                        
                    except Exception:
                        is_one = str(val).strip().lower() not in ("", "0", "none", "false")

                    if is_one:
                        exploded_osmid.append(str(osmid))

                        if hasattr(self, "field_name_categories") and field_name in self.field_name_categories:
                            poi_type = self.field_name_categories[field_name] 
                        else:
                            poi_type = field_name
                        
                        exploded_types.append(poi_type)
                        exploded_coords.append((xy[0], xy[1]))

        arcpy.AddMessage(f"Number of exploded POIs ready for matching: {len(exploded_osmid)}")

        if not exploded_osmid:
            arcpy.AddWarning("No POIs found with the specified categories.")
            return
        
        poi_osmid = np.array(exploded_osmid)
        poi_types = np.array(exploded_types)
        poi_coords = np.array(exploded_coords, dtype=float)
                     
        
        arcpy.AddMessage(f"Loading node data for matching.")

        node_ids = np.array([row[0] for row in arcpy.da.SearchCursor(str(self.node_data), [self.schema_info["field_name_node_id"]])])
        node_coords = np.array([[row[0][0], row[0][1]] for row in arcpy.da.SearchCursor(str(self.node_data), ["SHAPE@XY"])])

        arcpy.AddMessage(f"Number of nodes loaded: {len(node_ids)}")

        POItree = KDTree(poi_coords)
        output = {
            self.schema_info["field_name_poi_nodeid"]: [], 
            self.schema_info["field_name_poi_finalid"]: [],
            self.schema_info["field_name_poi_type"]: [], 
            self.schema_info["field_name_poi_distance"]: [], 
            self.schema_info["field_name_poi_fftwalk"]: []
        }
        idx_nodes_to_pois = POItree.query_ball_point(node_coords, r=self.poi_distance)
        arcpy.AddMessage("Performing proximity matches between nodes and POIs...")
        for nodeid, node_coord, poi_indices in zip(node_ids, node_coords, idx_nodes_to_pois):
            if poi_indices:
            # if len(pois) > 0:
                dist = np.linalg.norm(poi_coords[poi_indices].astype(float) - node_coord, axis=1) * 3.28084
                fft_walk = dist / 4.4
                output[self.schema_info["field_name_poi_nodeid"]] += [str(nodeid)] * len(dist)
                output[self.schema_info["field_name_poi_finalid"]] += list(poi_osmid[poi_indices])
                output[self.schema_info["field_name_poi_type"]] += list(poi_types[poi_indices])
                output[self.schema_info["field_name_poi_distance"]] += list(dist)
                output[self.schema_info["field_name_poi_fftwalk"]] += list(fft_walk)

                
        df = pd.DataFrame(output)
        self.match_table = self.scenario_fgdb / self.schema_info["fc_matched_poi_table"]
        arcpy.AddMessage(f"Saving to scenario geodatabase SeDF at {datetime.now().strftime('%H:%M:%S')}")
        # Spatially enabled DataFrame save - Slow but there are several million rows to write.
        
        self.df = df[df[self.schema_info["field_name_poi_type"]] != "Origins"].copy()
        
        # Some POIs may match to the same network node more than once; in these cases, we want to group by
        # the matched network node id, POI id, and POI category, and then pick the minimum distance.
        # This avoids getting multiple match results for the same network node + POI combination.
        self.df = self.df.groupby([self.schema_info["field_name_poi_nodeid"], self.schema_info["field_name_poi_finalid"],self.schema_info["field_name_poi_type"]]).agg({self.schema_info["field_name_poi_distance"]:"min", self.schema_info["field_name_poi_fftwalk"]:"min"}).reset_index()
        self.df.spatial.to_table(self.match_table, sanitize_columns=True)
        arcpy.management.AddIndex(
            in_table=str(self.match_table),
            fields=self.schema_info["field_name_poi_type"],
            index_name="poi_type_index",
            unique="NON_UNIQUE",
            ascending="NON_ASCENDING"
        )
        arcpy.management.AddIndex(
            in_table=str(self.match_table),
            fields=self.schema_info["field_name_poi_nodeid"],
            index_name="node_osmid_index",
            unique="NON_UNIQUE",
            ascending="NON_ASCENDING"
        )

    def summarize_pois(self):
        arcpy.AddMessage(f"Summarizing POIs matches {datetime.now().strftime('%H:%M:%S')}")

        if not hasattr(self, "df") or self.df is None or (hasattr(self, "df") and getattr(self, "df").empty):
            arcpy.AddWarning("summarize_pois: no match DataFrame (self.df) to summarize. Exiting.")
            return
        
        df = self.df.dropna(subset=[self.schema_info["field_name_poi_finalid"]])
        
        summary = self.df.groupby([self.schema_info["field_name_poi_nodeid"], self.schema_info["field_name_poi_type"]]).agg(
            poi_count=(self.schema_info["field_name_poi_finalid"], "nunique"),
            min_distance=(self.schema_info["field_name_poi_distance"], "min")
        ).reset_index()

        arcpy.AddMessage("Creating pivot table...")
        self.summary_pivot = summary.pivot(index=self.schema_info["field_name_poi_nodeid"], columns=self.schema_info["field_name_poi_type"], values=["poi_count", "min_distance"])
        self.summary_pivot.columns = [f"{stat}_{self.categories_field_name[cat]}" for stat, cat in self.summary_pivot.columns]
        count_fields = [c for c in self.summary_pivot if "poi_count" in c]
        self.summary_pivot = self.summary_pivot.reset_index()
        self.summary_pivot["total_pois"] = self.summary_pivot[count_fields].sum(axis=1)
        arcpy.AddMessage(f"Saving pivot table to geodatabase {datetime.now().strftime('%H:%M:%S')}")
        summary_pivot_table = self.scenario_fgdb / self.schema_info["fc_matched_poi_summary_table"]
        self.summary_pivot.spatial.to_table(summary_pivot_table, sanitize_columns=True)


        node_fields = [f.name for f in arcpy.ListFields(str(self.node_data))]
        summary_fields = [col for col in self.summary_pivot.columns if col != self.schema_info["field_name_poi_nodeid"]]
        fields_to_delete = [f for f in summary_fields if f in node_fields]
        arcpy.AddMessage(f"Deleting old summary fields {datetime.now().strftime('%H:%M:%S')}")
        if fields_to_delete:
            arcpy.DeleteField_management(str(self.node_data), fields_to_delete) #if it already has these fields delete them
        arcpy.AddMessage(f"Joining new summary fields {datetime.now().strftime('%H:%M:%S')}")
        arcpy.JoinField_management(str(self.node_data), self.schema_info["field_name_node_id"], str(summary_pivot_table), self.schema_info["field_name_poi_nodeid"])

    def get_category_counts(self):
        fields_to_names = {'cultural_facilities': 'Cultural facilities',
        'public_institutions': 'Public institutions',
        'parks_and_nature': 'Parks and Nature',
        'grocery_stores': 'Grocery stores',
        'Sports_centers': 'Sports centers',
        'retail': 'Retail',
        'transportation': 'Transportation',
        'faith_organizations': 'Faith organizations',
        'restaurants': 'Restaurants',
        'health_services': 'Health services',
        'educational_facilities': 'Educational facilities'}
        category_counts = {v:0 for _,v in fields_to_names.items()}
        id_checks = []
        with arcpy.da.SearchCursor(str(self.poi_data), [self.schema_info["field_name_poi_finalid"]] + list(fields_to_names.keys())) as sc:
            for row in sc:
                if row[0] not in id_checks:
                    for i,f in enumerate(list(fields_to_names.keys())):
                        category_counts[fields_to_names[f]] += row[i+1]
                    id_checks.append(row[0])
        return category_counts

    def get_nodes_by_modes(self):
        modes = {self.schema_info["field_name_bicycle_mode"]:[], self.schema_info["field_name_pedestrian_mode"]:[], self.schema_info["field_name_vehicle_mode"]:[]}
        with arcpy.da.SearchCursor(str(self.scenario_fgdb/self.schema_info["fc_name_integrated_nodes"]), [self.schema_info["field_name_node_id"], self.schema_info["field_name_vehicle_mode"], self.schema_info["field_name_bicycle_mode"], self.schema_info["field_name_pedestrian_mode"]]) as sc:
            for row in sc:
                if row[1] == 1:
                    modes[self.schema_info["field_name_vehicle_mode"]].append(row[0])
                if row[2] == 1:
                    modes[self.schema_info["field_name_bicycle_mode"]].append(row[0])
                if row[3] == 1:
                    modes[self.schema_info["field_name_pedestrian_mode"]].append(row[0])
        return modes

    def create_figure(self):
        fig = plt.figure(figsize=(11, 8.5))
        row_heights = [.9, .1]
        column_widths = [.9, .1]
        gs = gridspec.GridSpec(nrows=len(row_heights), ncols=len(column_widths), figure=fig, height_ratios=row_heights, width_ratios=column_widths, hspace=.8, wspace=.8)
        ax_plot = fig.add_subplot(gs[0,0])
        ax_plot_legend = fig.add_subplot(gs[0,1])
        ax_plot.ticklabel_format(style='plain', axis='y')
        formatter = mticker.FuncFormatter(lambda x, p: format(int(x), ','))
        ax_plot.yaxis.set_major_formatter(formatter)
        ax_desc = fig.add_subplot(gs[1,0:2])
        ax_desc.tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
        ax_desc.ticklabel_format(useOffset=False, style="plain")
        return ax_plot, ax_plot_legend, ax_desc

    def create_summary_report(self):
        arcpy.AddMessage("Creating report figures...")
        pdfName = f"{self.scenario_name}_poi_summarystats_{self.process_date}.pdf"
        pdfPath = self.scenario_folder / pdfName
        sns.set_theme(style="white")
        unique_categories = self.df[self.schema_info["field_name_poi_type"]].unique()
        count_columns = [col for col in self.summary_pivot.columns if "poi_count" in col]
        if "point_count_origins" in count_columns:
            count_columns.remove("point_count_origins")
        count_columns_rename = {c:self.field_name_categories[c.replace("poi_count_", "")] for c in count_columns}
        dist_columns = [col for col in self.summary_pivot.columns if "min_distance" in col]
        if "min_distance_origins" in dist_columns:
            dist_columns.remove("min_distance_origins")
        dist_columns_rename = {c:self.field_name_categories[c.replace("min_distance_", "")] for c in dist_columns}
        mode_ids = self.get_nodes_by_modes()
        sum_count = self.summary_pivot[count_columns].rename(columns=count_columns_rename).sum().reset_index().rename(columns={0:"count"})
        sum_count_walk = self.summary_pivot[self.summary_pivot[self.schema_info["field_name_poi_nodeid"]].isin(mode_ids[self.schema_info["field_name_pedestrian_mode"]])][count_columns].rename(columns=count_columns_rename).sum().reset_index().rename(columns={0:"count"})
        sum_count_bike = self.summary_pivot[self.summary_pivot[self.schema_info["field_name_poi_nodeid"]].isin(mode_ids[self.schema_info["field_name_bicycle_mode"]])][count_columns].rename(columns=count_columns_rename).sum().reset_index().rename(columns={0:"count"})
        sum_count_road = self.summary_pivot[self.summary_pivot[self.schema_info["field_name_poi_nodeid"]].isin(mode_ids[self.schema_info["field_name_vehicle_mode"]])][count_columns].rename(columns=count_columns_rename).sum().reset_index().rename(columns={0:"count"})
        #avg_count = self.summary_pivot[count_columns].rename(columns=count_columns_rename).mean().reset_index().rename(columns={0:"count"})
        #med_dist = self.summary_pivot[dist_columns].rename(columns=dist_columns_rename).median().reset_index().rename(columns={0:"median"})
        category_counts = self.get_category_counts()
        

        with PdfPages(pdfPath) as pdfobj:


            xs = [x[0] for x in sorted(category_counts.items())]
            ys = [x[1] for x in sorted(category_counts.items())]
            #create boxplots of the categories
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Total number of Points of Interest by category in the project area."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.barplot(x=xs, y=ys, hue=xs, legend=True,
                        ax=ax_plot, palette=sns.color_palette("hls", len(xs)))
            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Total Points in Category")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150, bbox_inches='tight')


            #total by category for matched nodes
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Total number of matched Points of Interest by category."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.barplot(x='index', y='count', hue='index', data=sum_count.sort_values("index"), legend=True,
                         ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Total POI Matches by Category")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150)

            #total by category for matched nodes for road
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Total number of matched Points of Interest by category for nodes on the vehicle network."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.barplot(x='index', y='count', hue='index', data=sum_count_road.sort_values("index"), legend=True,
                         ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Total POI Matches on\nVehicle Networkby Category")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150)

            #total by category for matched nodes for road
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Total number of matched Points of Interest by category for nodes on the bicycle network."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.barplot(x='index', y='count', hue='index', data=sum_count_bike.sort_values("index"), legend=True,
                         ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Total POI Matches on\nBicycle Networkby Category")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150)

            #total by category for matched nodes for road
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Total number of matched Points of Interest by category for nodes on the pedestrian network."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.barplot(x='index', y='count', hue='index', data=sum_count_walk.sort_values("index"), legend=True,
                         ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Total POI Matches on\nPedestrian Networkby Category")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150)

            #create boxplots of the categories
            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Distribution of distances from Network Junctions to the Point of Interest by category.\nEuclidean distances are in feet."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.boxplot(x=self.schema_info["field_name_poi_type"], y='distance', hue=self.schema_info["field_name_poi_type"], data=self.df.sort_values(self.schema_info["field_name_poi_type"]), legend=True,
                        ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))
            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Distance between Network\nJunction and POI (ft)")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150, bbox_inches='tight')

            ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            desc_text = "Distribution of Free Flow Time for walking from Network Junctions to the Point of Interest by category."
            ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            sns.boxplot(x=self.schema_info["field_name_poi_type"], y='fft_walk', hue=self.schema_info["field_name_poi_type"], data=self.df.sort_values(self.schema_info["field_name_poi_type"]), legend=True,
                         ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))
            ax_plot.set_xlabel("POI Category")
            ax_plot.set_ylabel("Free Flow Time (walking) between\nNetworkJunction and POI")
            ax_plot.get_xaxis().set_visible(False)
            handles, labels = ax_plot.get_legend_handles_labels()
            ax_plot_legend.legend(handles, labels, title="POI Category")
            ax_plot_legend.set_axis_off()
            ax_plot.get_legend().remove()
            pdfobj.savefig(dpi=150)

            # ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            # desc_text = "Average number of matches for a Network Junction by the POI category."
            # ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            # sns.barplot(x='index', y='count', hue='index', data=avg_count.sort_values("index"), legend=True,
            #             ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            # ax_plot.set_xlabel("POI Category")
            # ax_plot.set_ylabel("Average POI matches by category")
            # ax_plot.get_xaxis().set_visible(False)
            # handles, labels = ax_plot.get_legend_handles_labels()
            # ax_plot_legend.legend(handles, labels, title="POI Category")
            # ax_plot_legend.set_axis_off()
            # ax_plot.get_legend().remove()
            # pdfobj.savefig(dpi=150)

            # ax_plot, ax_plot_legend, ax_desc = self.create_figure()
            # desc_text = "Median distance to matches for a Network Junction by the POI category."
            # ax_desc.text(.02, .5, desc_text, ha='left',va='center')
            # sns.barplot(x='index', y='median', hue='index', data=med_dist.sort_values("index"), legend=True,
            #             ax=ax_plot, palette=sns.color_palette("hls", len(unique_categories)))

            # ax_plot.set_xlabel("POI Category")
            # ax_plot.set_ylabel("Median Distance to POI matches by category")
            # ax_plot.get_xaxis().set_visible(False)
            # handles, labels = ax_plot.get_legend_handles_labels()
            # ax_plot_legend.legend(handles, labels, title="POI Category")
            # ax_plot_legend.set_axis_off()
            # ax_plot.get_legend().remove()
            # pdfobj.savefig(dpi=150)
        os.startfile(str(pdfPath))
