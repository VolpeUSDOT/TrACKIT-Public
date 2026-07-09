# Step 3: Access Analysis and Metrics

The next few steps finalize the creation of a routable network, compute a matrix of shortest paths between all network nodes, and then calculate various accessibility measures.

## Step 3A: Convert Networks to Directed Graphs for Analysis

This step creates a directed graph for each mode’s pre- and postnetwork and saves them as Python-readable (pickled) objects.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |

Expected outputs (visible from File Explorer):

- ProjectName_project\Scenario1\NET1234abcd_mode_pre.net
- ProjectName_project\Scenario1\NETabcd1234_mode_post.net

Expected geodatabase outputs (visible from within ArcGIS):

- ProjectName_project\Scenario1\Scenario1.gdb\networks

Make sure to check that the “.net” files exist and that their file size is reasonable (a file size that is as small as ~1KB indicates an error in running this step) before moving on to the next step.

## Step 3B: Calculate Distances Between Origins and Destinations

This step produces a set of shortest path origin-destination matrices for each directed graph produced in [Step 3A](step3/#step-3a-convert-networks-to-directed-graphs-for-analysis).

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| Scope of vehicle or truck/pedestrian/bicycle analysis (miles) | These parameters allow for a distinct spatial scope for each travel mode when constructing OD matrices, ensuring access calculations use mode-appropriate catchments. For example, to assess destinations reachable within the same travel time, a pedestrian catchment can be smaller than a vehicle catchment because vehicles typically travel farther in the same time. The mode-specific scope should not exceed the scenario radius defined in Step 2A. | 20/3/10 |

Expected outputs (visible from File Explorer):

- ProjectName_project\Scenario1\Scenario1_mode_pre_dist_matrix.dist
- ProjectName_project\Scenario1\Scenario1_mode_post_dist_matrix.dist

Make sure to check that the “.dist” files exist and that their file size is reasonable (not 1KB) before moving on to the next step.

## Step 3C: Calculate Accessibility Measures (Travel Shed Areas)
*Optional Step*

This step generates travel shed isochrones for the selected origin centroids using the origin–destination matrices produced in [Step 3B](step3/#step-3b-calculate-distances-between-origins-and-destinations), producing separate results for prenetwork and postnetwork conditions and for each travel mode. Isochrones are created for every selected travel time threshold and origin GEOID, and the resulting geometries, along with the corresponding area measurements in square miles, are saved in the relevant mode- and network-specific feature classes.

Before running the tool, the user should one origin node of interest using the “Select” tool. For simplicity, it is not possible to generate travel sheds for more than one origin at a time.

Each additional run of this tool computes and appends new travel sheds to the existing travel shed feature class produced during earlier runs. The tool then automatically adds the feature class to the map and applies a definition query to the dataset to show just the travel sheds produced during the most recent run of the tool. Travel sheds produced from prior runs can be viewed by removing the definition query from the travel shed feature class.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| Modes | Checkboxes to indicate the modes on which to run the tool. A separate feature class will be created for each mode. | vehicle, pedestrian, bike |
| Pre/post network type | Checkboxes to indicate the network(s) on which to run the tool. A  separate feature class will be created for each network (and mode).| prenetwork, postnetwork |
| Travel time Threshold | Checkboxes to indicate the travel time thresholds on which to run the tool. Travel sheds for multiple thresholds will be appended to the relevant feature class. | 15, 30 |
| Origin Layer | The origin nodes layer with an origin selected from which the travel sheds will be calculated. There should only be one origin selected. The tool will automatically select the origin nodes layer if it is present on the map, or it will load it onto the map if not present. | GEOID_250173523003003 |
| Origin Layer validated? | Checkbox to prompt the tool to check the origin layer for errors (e.g., ensuring exactly one origin is selected). | True |

Expected geodatabase outputs (visible from within ArcGIS):

- ProjectName_project\Scenario1\Scenario1.gdb\travel_sheds_mode_pre
- ProjectName_project\Scenario1\Scenario1.gdb\travel_sheds_mode_post

## Step 3D: Calculate Accessibility Measures (Cumulative)
*Optional Step*

This step computes cumulative metrics from the origin–destination matrices produced in [Step 3B](step3/#step-3b-calculate-distances-between-origins-and-destinations). The metrics indicate the total number of POI destinations reachable within each given travel time threshold and are calculated for each selected mode and POI category, across all origin GEOIDs. By default, the tool performs calculations for both prenetwork and postnetwork conditions. Each execution creates a new output folder, labeled with a timestamp. Results are saved into the output folder as .CSV files and as Python-readable (pickled) objects for further analysis.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| POI categories | Checkboxes to indicate the POI categories on which to run the tool. | Grocery stores |
| Modes | Checkboxes to indicate the modes on which to run the tool. | vehicle, pedestrian, bike |
| Threshold (minutes) | Checkboxes to indicate the travel time thresholds on which to run the tool. | 15, 30 |

Expected outputs (visible from File Explorer):

- ProjectName_project\Scenario1\Scenario1_cumu_YYMMDDHHMM\Scenario1_mode_cumu.metrics
- ProjectName_project\Scenario1\Scenario1_cumu_YYMMDDHHMM\Scenario1_mode_cumu.csv

The data generated by this tool is in the format shown below:

| Column Field Name | Description |
| :--- | :--- |
| origin_id | Origin GEOID |
| within_# | Number of accessible destinations within time threshold (#) |
| mode | Travel mode |
| network | Prenetwork or postnetwork |
| poi_type | POI category |
| population | Population in origin Census tract |
| *other_demographic_field* | Additional demographic field(s) added for weighting

## Step 3E: Calculate Accessibility Measures (Dual)
*Optional Step*

This step computes dual metrics from the origin–destination matrices produced in [Step 3B](step3/#step-3b-calculate-distances-between-origins-and-destinations). The metrics indicate the travel time in seconds to the Nth closest destination for a given POI category across all origin GEOIDs. Dual metrics are appropriate when you want to avoid the arbitrary time cutoffs of cumulative metrics, which can falsely indicate zero access if a destination falls just outside a rigid time boundary. Dual metrics are also more appropriate for POIs like hospitals where more is not always better and just a couple of options suffice. The ideal N is simply the number of POIs of that type needed to provide adequate consumer choice.

By default, the tool performs calculations for both prenetwork and postnetwork conditions. Each execution creates a new output folder, labeled with a timestamp. Results are saved into the output folder as .CSV files and as Python-readable (pickled) objects for further analysis. Note that the tool can only calculate travel times within the limits of the scenario network, meaning if the Nth closest destination is outside of this network, travel times will not be computable.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| Modes | Checkboxes to select the modes on which to run the tool. | vehicle, pedestrian, bike |
| Thresholds: POI Category | Pulldown to select the POI categories on which to run the tool. | Grocery stores |
| Thresholds: Number of destinations | Nth closest destination that should be used compute travel times. This value can vary based on POI category. | 3 |

Expected outputs (visible from File Explorer):

- ProjectName_project\Scenario1\Scenario1_dual_YYMMDDHHMM\Scenario1_mode_dual.metrics
- ProjectName_project\Scenario1\Scenario1_dual_YYMMDDHHMM\Scenario1_mode_dual.csv

The data generated by this tool is in the format shown below:

| Column Field Name | Description |
| :--- | :--- |
| origin_id | Origin GEOID |
| travel_time_sec | Travel time in seconds |
| nth_destination | Nth closest destination used to compute travel times |
| mode | Travel mode |
| network | Prenetwork or postnetwork |
| poi_type | POI category |
| population | Population in origin Census tract |
| *other_demographic_field* | Additional demographic field(s) added for weighting

## Step 3F: Generate Reports and Visuals for Generated Metrics
*Optional Step*

This step generates an access report for metrics calculated in [Step 3D](step3/#step-3d-calculate-accessibility-measures-cumulative) and/or [Step 3E](step3/#step-3e-calculate-accessibility-measures-dual). If the “Generate maps in report?” option is selected, this step can take a long time to run, because it will generate a separate map for each combination of mode, POI category, and travel time threshold that is present in your computed metrics.

*Pro tip:* If you have included a large number of modes, POI categories, and travel time thresholds in [Step 3D](step3/#step-3d-calculate-accessibility-measures-cumulative), try generating a report *without* maps to start. Then, examine your report to see what combination of modes, POI categories, and travel time thresholds appear to have resulted in significant access changes. Then, re-run [Step 3D](step3/#step-3d-calculate-accessibility-measures-cumulative) focusing *only* on the combination of modes, POI categories, and travel time thresholds that have resulted in significant access changes. Re-run [Step 3F](step3/#step-3f-generate-reports-and-visuals-for-generated-metrics) using this newer, narrower set of metrics—this time with the “Generate maps in report?” option turned on. This reduces report generation time while still allowing you to inspect significant results.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| Metrics to include in report | Pulldown to select the metrics folder from [Step 3D](step3/#step-3d-calculate-accessibility-measures-cumulative) or [Step 3E](step3/#step-3e-calculate-accessibility-measures-dual) on which to run the tool. | Scenario1_cumu_2607041200 |
| Files to run metrics on | Checkboxes to select the pickled metrics files on which to run the tool. Visuals will be reported for each selected file. | Scenario1_vehicle_cumu.metrics |
| Field to use for report weighting | Pulldown to select the demographic field (e.g., population or housing units) used to weight the report's metrics. | population |
| Generate maps in report? | Checkbox to select whether or not the report will include maps. Including maps will result in longer run times. | N/A |
| Keep maps in this ArcGIS Pro Project? | Checkbox to select whether or not the ArcGIS Maps generated (if any) will be saved as individual Maps in the ArcGIS Pro project. If deselected, these maps will be deleted after the report is generated. Deleting maps can keep the ArcGIS workspace cleaner but will add to the run time. | N/A |

Expected outputs (visible from File Explorer):

- ProjectName_project\Scenario1\Scenario1_cumu_YYMMDDHHMM\census_blocks_demographic_field.png
- ProjectName_project\Scenario1\Scenario1_cumu_YYMMDDHHMM\mode_poiCategory_threshold_cumu.png
- ProjectName_project\Scenario1\Scenario1_cumu_YYMMDDHHMM\report_YYMMDDHHMM_cumu_mode1_mode2_mode3.pdf

Expected geodatabase outputs (visible from within ArcGIS):

- If "Custom Point" origins:
    - ProjectName_project\Scenario1\Scenario1.gdb\buffered_origin_nodes
    - ProjectName_project\Scenario1\Scenario1.gdb\metrics_origin_nodes
- If "Custom Polygon" origins:
    - ProjectName_project\Scenario1\Scenario1.gdb\metrics_custom_origin_polygons_template
- If "Census Block" origins:
    - ProjectName_project\Scenario1\Scenario1.gdb\metrics_area_census_blocks_projected

The metrics PDF report includes the following visuals:

| Order | Description | Cumulative/Dual | Saved separately? |
| :--- | :--- | :--- | :--- |
| 1 | **Origin distribution map** weighted by selected demographic data | Both | Yes, as PNG |
| 2 | **Node access ratio plots** showing the ratio of accessible network nodes with associated POIs in the scenario network compared to the original network, by travel time and travel mode | Both | No, only in PDF report |
| 3 | **Line plots** displaying the number of POIs accessible to the average resident across origins at various travel time thresholds and modes | Cumulative | No, only in PDF report |
| 4 | **Lollipop charts** showing the average magnitude of access change from the original network to the scenario network | Both | No, only in PDF report |
| 5 | **Stacked bar charts** of the total population experiencing different access impacts (increase, decrease, no change) | Both | No, only in PDF report |
| 6 | **Access ratio maps** comparing results in the scenario network compared to the original network. For Custom Point origins, buffered points are used. Note that maps will only be generated if “Generate maps in report?” is checked. | Both | Yes, as PNGs |

!!! info "Note on Access Change Thresholds in Report Visuals"
    In the stacked bar charts, access impacts are grouped into simple categories indicating whether users experienced an overall gain, loss, or no change in their ability to reach destinations. On the access ratio maps, these changes are visualized in finer detail using a 1% and 3.5% rule. Fluctuations of less than 1% in either direction are treated as "No Change". If access improves or worsens by between 1% and 3.5%, it is mapped as "Some" increase or decrease in access. Finally, any change greater than 3.5% in either direction is highlighted as a "Significant" increase or decrease.

## Step 3G: Trace Shortest Path Between Two Network Nodes
*Optional Step*

This tool maps the shortest path between two selected network nodes on a chosen network and calculates the free‑flow travel time for each route. These results can be useful in assessing project impacts on specific trips, or for troubleshooting issues.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenario | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset). | Scenario1 |
| Scenario Modes | Checkboxes to select the modes on which to run the tool. | Pedestrian |
| Network Type | Checkboxes to indicate the network(s) on which to run the tool. | prenetwork, postnetwork |
| Origin ID | Node ID (network_node_id) for the node from which the path should start. This feature can be selected from “integrated_nodes_for_analysis.” | 197515616 |
| Destination ID | Node ID (network_node_id) for the node where the path should end. This feature can be selected from “integrated_nodes_for_analysis.” | 161940470 |

Expected geodatabase outputs (visible from within ArcGIS):

- ProjectName_project\Scenario1\Scenario1.gdb\shortest_paths
