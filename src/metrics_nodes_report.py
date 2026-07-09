from pathlib import Path
import json
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
import time

from metrics_accessibility import metric


class metric_full(metric):
    def __init__(self, projectFolder, scenarioName:str, poi_type_list:list = None, scenario_modes:list = ["walk"]):
        super().__init__(projectFolder, scenarioName, poi_type_list, scenario_modes)

    def create_line_plots(self, pdfPath:Path, total_minutes:float=60):
        page_width = self.report_settings["report_settings"]["width_in"]
        page_height = self.report_settings["report_settings"]["height_in"]
        dpi = self.report_settings["report_settings"]["dpi"]
        pal = self.report_settings["colors_for_categories"]
        self.poi_df = self.load_pois_and_filter()
        poi_relevant_nodes = self.poi_df[self.poi_node_field].unique()
        
        with PdfPages(pdfPath) as pdf:
            for mode in self.scenario_modes:
                output = {"X":[], "Y_PRENETWORK":[], "Y_POSTNETWORK":[], "POSTABOVE":[]}
                dm_pre = self.load_distance_matrix(mode, "prenetwork")
                dest_cols_to_melt = ["from"] + list(set(dm_pre.columns).intersection(poi_relevant_nodes))
                dm_pre = dm_pre[dest_cols_to_melt]
                dm_pre.set_index("from", inplace=True)
                dm_post = self.load_distance_matrix(mode, "postnetwork")
                dest_cols_to_melt = ["from"] + list(set(dm_post.columns).intersection(poi_relevant_nodes))
                dm_post = dm_post[dest_cols_to_melt]
                dm_post.set_index("from", inplace=True)
                dm_pre = dm_pre / 60
                dm_post = dm_post / 60
                v_pre = dm_pre.values
                v_post = dm_post.values
                fm_pre = np.isfinite(v_pre)
                fm_post = np.isfinite(v_post)
                print(mode)
                for i in np.arange(.5, total_minutes, .5): 
                    lta_pre = np.where((v_pre<=i) & fm_pre, 1, 0)
                    lta_post = np.where((v_post<=i) & fm_post, 1, 0)
                    output["X"].append(i)
                    output["Y_PRENETWORK"].append(np.sum(lta_pre))
                    output["Y_POSTNETWORK"].append(np.sum(lta_post))
                    if np.sum(lta_pre) < np.sum(lta_post):
                        output["POSTABOVE"].append("ABOVE")
                    else:
                        output["POSTABOVE"].append("BELOW")

                df_output = pd.DataFrame(output)
                df_output["Y_POSTNETWORK_SQRT"] = np.sqrt(df_output["Y_PRENETWORK"])
                df_output["Y_PRENETWORK_SQRT"] = np.sqrt(df_output["Y_POSTNETWORK"])
                minoriginal = min(df_output["Y_PRENETWORK"].min(), df_output["Y_POSTNETWORK"].min())
                maxoriginal = max(df_output["Y_PRENETWORK"].max(), df_output["Y_POSTNETWORK"].max())
                interval = int((maxoriginal - minoriginal) / 5)
                zerostoadd = 10 ** (len(str(interval))-1)
                interval = helper_functions.round_place(interval, zerostoadd)
                print(interval)
                interval = max(1, int(interval))  # <--- ADD SAFEGUARD
                ticks = [i for i in range(0, int(maxoriginal)+interval, interval)]
                print(ticks)
                ticks_sqrt = [np.sqrt(x) for x in ticks]
                print(ticks_sqrt)
                ticks_labels = [format(int(x), ',') for x in ticks]
                axes = self.create_figure_with_panels((page_width, page_height),1,1)
                axes["ax1"].plot(df_output["X"], df_output["Y_PRENETWORK_SQRT"],
                                linewidth=.7, color="k", label="Prenetwork")
                axes["ax1"].plot(df_output["X"], df_output["Y_POSTNETWORK_SQRT"],
                            linewidth=.7, color="r", label="Prenetwork")            
                handles, labels = axes["ax1"].get_legend_handles_labels()
                axes["axLeg"].legend(handles, labels, title="Network Type", ncol=3, loc='upper center')
                axes["ax1"].set_xlabel = "Travel in Minutes"
                axes["ax1"].set_ylabel = "Reachable Network Nodes"
                axes["ax1"].set_title = f"Number of Reachable Nodes\nby Mode {mode}"
                axes["ax1"].set_ylim([ticks_sqrt[0], ticks_sqrt[-1]])
                axes["ax1"].set_yticks(ticks_sqrt)
                axes["ax1"].set_yticklabels(ticks_labels)


                axes["axLeg"].set_axis_off()
                desc_text = f"This figure shows a plot of the total number of network nodes\nreachable in the minutes interval along the x-axis.\nThe total is cumulative. When the prenetwork line is above the postnetwork\nline there was a decrease in access.\nGenerally, vehicles will have access to fewer of the network nodes.\nMode: {mode}"
                axes["axDesc"].text(.02, .5, desc_text, ha='left',va='center')
                print("save figure")
                plt.tight_layout()
                pdf.savefig()


                axes = self.create_figure_with_panels((page_width, page_height),1,1)
                axes["ax1"].plot(df_output["X"], df_output["Y_POSTNETWORK"] / df_output["Y_PRENETWORK"],
                                    color="k", lw=1, label="Scenario Network to Original Network")      
                handles, labels = axes["ax1"].get_legend_handles_labels()
                axes["axLeg"].legend(handles, labels, title="Ratio", ncol=1, loc='upper center')
                axes["ax1"].set_xlabel("Travel in Minutes")
                axes["ax1"].set_ylabel("Ratio")
                axes["ax1"].set_ylim([.5, 1.5])
                axes["ax1"].hlines(1, 0, 60, colors='k', linestyles='dashed', alpha=.5, lw=.5)

                axes["ax1"].set_title(f"Number of Reachable Nodes\n Scenario Network to Original Network by Mode {mode}")
                axes["axLeg"].set_axis_off()
                desc_text = f"This figure shows a plot of the ratio of number of postnetwork nodes\n to prenetwork nodes in the minutes interval along thex-axis.\nThe total is cumulative. When the line is below 1\nthere was a decrease in access.\nMode: {mode}"
                axes["axDesc"].text(.02, .5, desc_text, ha='left',va='center')
                print("save figure")
                plt.tight_layout()
                pdf.savefig()
        try:
            os.startfile(pdfPath)
        except:
            pass
        return pdfPath
    
    def create_overview_plot(self, axesDict:dict, pdfWriter:PdfPages, total_minutes:float=60, descText:str=None):
        self.poi_df = self.load_pois_and_filter()
        poi_relevant_nodes = self.poi_df[self.poi_node_field].unique()
        mode_to_name = {v:k for k,v in self.settings_info["mode_name_matching"].items()}
        legendSet = False
        for axIndx, mode in enumerate(self.scenario_modes):
            axKey = f"ax{axIndx+1}"
            output = {"X":[], "Y_PRENETWORK":[], "Y_POSTNETWORK":[], "POSTABOVE":[]}
            dm_pre = self.load_distance_matrix(mode, "prenetwork")
            dest_cols_to_melt = ["from"] + list(set(dm_pre.columns).intersection(poi_relevant_nodes))
            dm_pre = dm_pre[dest_cols_to_melt]
            dm_pre.set_index("from", inplace=True)
            dm_post = self.load_distance_matrix(mode, "postnetwork")
            dest_cols_to_melt = ["from"] + list(set(dm_post.columns).intersection(poi_relevant_nodes))
            dm_post = dm_post[dest_cols_to_melt]
            dm_post.set_index("from", inplace=True)
            dm_pre = dm_pre / 60
            dm_post = dm_post / 60
            v_pre = dm_pre.values
            v_post = dm_post.values
            fm_pre = np.isfinite(v_pre)
            fm_post = np.isfinite(v_post)
            print(mode)
            for i in np.arange(.5, total_minutes, .5): 
                lta_pre = np.where((v_pre<=i) & fm_pre, 1, 0)
                lta_post = np.where((v_post<=i) & fm_post, 1, 0)
                output["X"].append(i)
                output["Y_PRENETWORK"].append(np.sum(lta_pre))
                output["Y_POSTNETWORK"].append(np.sum(lta_post))
                if np.sum(lta_pre) < np.sum(lta_post):
                    output["POSTABOVE"].append("ABOVE")
                else:
                    output["POSTABOVE"].append("BELOW")

            df_output = pd.DataFrame(output)
            df_output["Y_POSTNETWORK_SQRT"] = np.sqrt(df_output["Y_PRENETWORK"])
            df_output["Y_PRENETWORK_SQRT"] = np.sqrt(df_output["Y_POSTNETWORK"])
            minoriginal = min(df_output["Y_PRENETWORK"].min(), df_output["Y_POSTNETWORK"].min())
            maxoriginal = max(df_output["Y_PRENETWORK"].max(), df_output["Y_POSTNETWORK"].max())
            interval = int((maxoriginal - minoriginal) / 5)
            zerostoadd = 10 ** (len(str(interval))-1)
            interval = helper_functions.round_place(interval, zerostoadd)
            print(interval)
            interval = max(1, int(interval))  # <--- ADD SAFEGUARD
            ticks = [i for i in range(0, int(maxoriginal)+interval, interval)]
            print(ticks)
            ticks_sqrt = [np.sqrt(x) for x in ticks]
            print(ticks_sqrt)
            ticks_labels = [format(int(x), ',') for x in ticks]
            
            axesDict[axKey].plot(df_output["X"], df_output["Y_POSTNETWORK"] / df_output["Y_PRENETWORK"],
                                color="k", lw=1, label="Scenario Network to Original Network")
            handles, labels = axesDict[axKey].get_legend_handles_labels()
            if legendSet is False:
                axesDict["axLeg"].legend(handles, labels, title="Ratio", ncol=1, loc='upper center')
                axesDict["axLeg"].set_axis_off()
                legendSet = True
            if axIndx == len(self.scenario_modes)-1:
                axesDict[axKey].set_xlabel("Travel in Minutes from Origins")
            else:
                axesDict[axKey].get_xaxis().set_visible(False)
            axesDict[axKey].set_title(f"{mode_to_name[mode]}")
            
            #axesDict[axKey].set_ylabel("Ratio")
            # safe division: produce float series with NaN where denom == 0
            ratio = df_output["Y_POSTNETWORK"].astype(float).div(df_output["Y_PRENETWORK"].replace(0, np.nan))
            # drop NaN/inf for computing limits
            ratio_clean = ratio.replace([np.inf, -np.inf], np.nan).dropna()
            if not ratio_clean.empty:
                max_val = ratio_clean.max()
                min_val = ratio_clean.min()
                axesDict[axKey].set_ylim([round(min_val - 0.2, 1), round(max_val + 0.2, 1)])
            else:
                # fallback to a sensible default around 1.0 when no valid ratio data
                axesDict[axKey].set_ylim([0.95, 1.05])
            
            axesDict[axKey].yaxis.set_major_locator(mticker.MultipleLocator(0.1))
           
            axesDict[axKey].hlines(1, 0, total_minutes, colors='k', linestyles='dashed', alpha=.5, lw=.5)

            if descText is None:
                descText = f"This figure shows a plot of the ratio of number of postnetwork nodes\n to prenetwork nodes in the minutes interval along thex-axis.\nThe total is cumulative. When the line is below 1\nthere was a decrease in access.\nMode: {mode}"
            axesDict["axDesc"].text(.03, .5, descText, ha='left',va='center')
            
        plt.tight_layout()
        pdfWriter.savefig()
        return axesDict
    
    def create_figure_with_panels(self, figsize, rows=1, columns=1):
        fig = plt.figure(figsize=figsize)
        row_area = (1 -.2 - .1) / rows
        column_area = 1 / columns
        row_heights = [row_area for i in range(0,rows)] +[.2, .1]
        column_widths = [column_area for i in range(0,columns)]
        gs = gridspec.GridSpec(nrows=len(row_heights), ncols=len(column_widths), figure=fig, height_ratios=row_heights, width_ratios=column_widths)
        axes = {"axLeg":None, "axDesc":None}
        for r in range(0, rows):
            for c in range(0, columns):
                axes[f"ax{r+c+1}"] = fig.add_subplot(gs[r,c])
        axes["axLeg"] = fig.add_subplot(gs[-2, 0:3])
        axes["axDesc"] = fig.add_subplot(gs[-1,0:3])
        axes["axDesc"].tick_params(labelbottom=0, labelleft=0, bottom=0, top=0, left=0, right=0)
        axes["axDesc"].ticklabel_format(useOffset=False, style="plain")

        return axes
    
    def create_direction_roses(self, threshold=15,buffer_dist=500):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        sedf_nodes = pd.DataFrame.spatial.from_featureclass(location = str(self.nodes_path))
        sedf_nodes["DEST_COORDS"] = sedf_nodes["SHAPE"].apply(lambda x: np.array([x.x, x.y]))
        utmsr = arcpy.SpatialReference(sedf_nodes.spatial.sr['wkid'])
        sedf_origins = pd.DataFrame.spatial.from_featureclass(location = str(self.origins_path))
        sedf_origins["ORIG_COORDS"] = sedf_origins["SHAPE"].apply(lambda x: np.array([x.x, x.y]))
        slice_angles = self.create_slices()
        outputWorkspace = helper_functions.drop_add_fgdb(self.project_folder/self.scenario_name, f"direction_roses_{timestamp}.gdb")
        fc = helper_functions.drop_add_featureclass(outputWorkspace, f"direction_wedges", "POLYGON", utmsr)
        helper_functions.drop_add_field(fc, self.schema_info["field_name_origin_id"], "TEXT", field_length=500)
        helper_functions.drop_add_field(fc, "COUNT", "LONG")
        helper_functions.drop_add_field(fc, "MODE", "TEXT")
        helper_functions.drop_add_field(fc, "NETWORK", "TEXT")
        helper_functions.drop_add_field(fc, "THRESHOLD", "DOUBLE")
        fields = ["SHAPE@", self.schema_info["field_name_origin_id"], "COUNT", "MODE", "NETWORK", "THRESHOLD"]

        self.poi_df = self.load_pois_and_filter()
        poi_relevant_nodes = self.poi_df[self.poi_node_field].unique()
        
        for mode in self.scenario_modes:
            for network in ["prenetwork", "postnetwork"]:
                dmw = self.load_distance_matrix(mode, network)
                dest_cols_to_melt = ["from"] + list(set(dmw.columns).intersection(poi_relevant_nodes))
                dm = pd.melt(
                    dmw,
                    id_vars="from",
                    value_vars=dest_cols_to_melt,
                    var_name="to",
                    value_name="distance",
                )
                dm = dm[np.isfinite(dm['distance'])]
                dm['distance'] = dm["distance"]/60
                dm = dm[dm["distance"] <= threshold]
                dm_c = dm.merge(sedf_nodes[[self.node_id_field, "DEST_COORDS"]], left_on="to",
                        right_on=self.node_id_field, how="left")
                dm_c = dm_c.merge(sedf_origins[[self.schema_info["field_name_origin_id"], "ORIG_COORDS"]], left_on="from",
                        right_on=self.schema_info["field_name_origin_id"], how="left")
                dm_c["ANGLES"] = self.get_angles(np.array(dm_c["ORIG_COORDS"].to_list()),
                                                np.array(dm_c["DEST_COORDS"].to_list()))
                dm_c["ANGLE_GROUP"] = -1
                for k,v in slice_angles.items():
                    dm_c["ANGLE_GROUP"] = np.where((dm_c["ANGLES"] >= v[0] ) & (dm_c["ANGLES"] < v[1]), k, dm_c["ANGLE_GROUP"])

                angle_counts = dm_c.groupby(["from", "ANGLE_GROUP"])["to"].count().reset_index()
                angle_counts.set_index("from", inplace=True)
                angle_counts.rename(columns={"to":"COUNT"}, inplace=True)
                minimal = sedf_origins[[self.schema_info["field_name_origin_id"], "ORIG_COORDS"]]
                minimal.set_index(self.schema_info["field_name_origin_id"], inplace=True)
                origins = minimal.to_dict()["ORIG_COORDS"]
                wedge_polygons = self.draw_wedges(origins, angle_counts, slice_angles, utmsr, buffer_dist)
                self.write_to_fc(fc, fields, origins, wedge_polygons, mode, network, threshold)
        return outputWorkspace

    def get_angles(self,center_point,points):
        delta = center_point - points
        sigma = np.rad2deg(np.arctan2(delta[:,0],delta[:,1]))
        compass_angles = np.where(sigma<0,sigma+360,sigma)
        return compass_angles
    
    def create_slices(self, slices=8):
        steps = 360 / slices
        slice_num = 0
        slice_angles = {}
        left_side = 0
        right_side = steps
        while right_side <= 360:
            slice_angles[slice_num] = [left_side,right_side]
            left_side += steps
            right_side += steps
            slice_num +=1
        return slice_angles
    
    def draw_wedges(self, origins, angle_counts, slice_angles, sr, max_buffer_dist):
        wedge_polygons = {k:[] for k in origins}
        wedge_centerline = {k:[] for k in origins}
        for o in origins:
            counts = angle_counts.loc[o].to_dict('records')
            opnt = np.array([origins[o][0],origins[o][1]])
            totvol = sum([v["COUNT"] for v in counts])
            cpnt = arcpy.Point(opnt[0],opnt[1])
            pg = arcpy.PointGeometry(cpnt, sr)
            buffer = pg.buffer(max_buffer_dist)
            #wedge_polygons[o].append([buffer,totvol,100,self.MAX_BUFFER_DIST])
            for x in counts:
                v = x['COUNT']
                k = x['ANGLE_GROUP']
                dist = max_buffer_dist * (v/totvol)
                if dist == 0:
                    dist = max_buffer_dist*.001
                distSq = dist*dist
                wa = slice_angles[k]
                try:
                    left = (opnt[0] - distSq * np.sin(np.deg2rad(wa[0])),opnt[1] - distSq* np.cos(np.deg2rad(wa[0])))
                    right = (opnt[0] - distSq * np.sin(np.deg2rad(wa[1])),opnt[1] - distSq* np.cos(np.deg2rad(wa[1])))
                    arrln = arcpy.Array([arcpy.Point(left[0],left[1]),arcpy.Point(right[0],right[1])])
                    topln = arcpy.Polyline(arrln)
                    mdpnt = topln.positionAlongLine(.5,True).centroid
                    centerLine = arcpy.Polyline(arcpy.Array([cpnt,mdpnt]))
                    arr = arcpy.Array([cpnt,arcpy.Point(left[0],left[1]),arcpy.Point(right[0],right[1]),cpnt])
                    polygon = arcpy.Polygon(arr)
                    
                    buffer = pg.buffer(dist)
                    wg = polygon.intersect(buffer,4)
                    wcl = buffer.intersect(centerLine,2)
                    wedge_polygons[o].append([wg, v, v/totvol, dist])
                    wedge_centerline[o].append([wcl, v, v/totvol, dist])
                except:
                    arcpy.AddWarning(f"Error drawing wedge {o}, {v}, {k}")

        return wedge_polygons
    
    def write_to_fc(self, fc, fields, origins, wedge_polygons, mode, network, threshold):
        for o in origins:
            with arcpy.da.InsertCursor(str(fc),fields) as ic:
                for seg in wedge_polygons[o]:
                    ic.insertRow([seg[0],o, seg[1],mode, network, threshold])

# proj_path = Path(r"E:\working\CoPDemo\CoP_TrACKIT_Demo\Centroids_project")
# pdfpath = proj_path/"testnodes.pdf"
# prj_fgdb = Path(r"E:\working\CoPDemo\CoP_TrACKIT_Demo\Centroids_project\Centroids_data.gdb")
# scenario_name = "Centroid_Scenario"
# m = metric_full(proj_path, prj_fgdb, scenario_name, None, ["vehicle", "pedestrian", "bike"])