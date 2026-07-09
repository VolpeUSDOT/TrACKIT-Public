
# Maintenance

## Manage Projects

By default, TrACKIT stores a local history of all projects you have ever created or imported using the TrACKIT toolbox and makes them accessible in the “Existing Project” drop down selector for the different TrACKIT tools. (Note: TrACKIT stores your project history information as a metadata file called projects.json in the TrACKIT code directory on your local computer. You should not need to manage or edit this file directly.) The TrACKIT toolbox offers several operations that are useful to manage your projects, if needed. These operations and their input parameters are described below.

### Operation 1: Rename Project
This operation renames the selected projects in the “Existing Project” dropdown list that is used in various tools. Files on the disk are not renamed.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| New Name for Project | New name for the project. | NewTest |

### Operation 2: Remove Project Name
This operation removes the selected project from the “Existing Project” dropdown list that is used in various tools. *Files on the disk are **not** deleted.*

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |

### Operation 3: Remove Project Name and Delete from Disk
This operation removes the selected project from the “Existing Project” dropdown list that is used in various tools, ***and*** *it deletes the relevant project files from the disk*.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |

### Operation 4: Remove Scenario Name
This operation removes the selected scenario from the “Scenario” dropdown list after a Project is selected. It also removes the scenario from the “project_scenarios” table. *Files on the disk are **not** deleted.*

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| Scenarios | Name of the scenario that you created in [Step 2A](step2/#step-2a-create-project-scenario-dataset) that you would like to remove. | Scenario1 |

### Operation 5: Remove Scenario Name and Delete from Disk
This operation removes the selected scenario from the “Scenario” dropdown list after a Project is selected, and it removes the scenario from the “project_scenarios” table. This operation ***also*** deletes the relevant scenario files from the disk.*

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |

### Operation 6: Export Project as Zip Archive
This operation can be used to share projects. It creates a zip file of all files and folders for a selected project. The zip file will be generated in the same folder as the project folder.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |

### Operation 7: Import Zip Archive as Project
This operation can be used to load in a shared project file. It imports the zip file created in the “Export Project as Zip Archive” operation.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Project Zip File | Path to the zip file to be extracted and imported. | Test_project.zip |
| Extract Zip to this Folder | Folder where the zip file contents will be extracted. Project will be added to the “Existing Project” dropdown list that is used in various tools. | Folder |

### Operation 8: Import Folder as Project
This operation imports an existing project folder so that it appears in the “Existing Project” dropdown list that is used in various tools.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Import This Project Folder | Folder that contains the project geodatabase and scenarios, ends with _project | Test_project |

## Redownload Project OSM Files

This tool allows for the selective regeneration of OSM files, providing an alternative to the full rerun required in [Step 1A](step1/#step-1a-download-base-osm-data). Any selected OSM data types will be redownloaded and will overwrite existing files in the project directory.

| Parameter Name | Description | Example |
| :--- | :--- | :--- |
| Existing Project | Name of the project that you created in [Step 1A](step1/#step-1a-download-base-osm-data). | Test |
| OSM Data Types | Options to redownload ways/network data (_ways.osm), Points of Interest (_poi.osm), and/or water features (_water.osm) from OSM. | All required .osm files |

Expected outputs (visible via File Explorer):

- ProjectName_project\ProjectName_poi.osm*
- ProjectName_project\ProjectName_water.osm
- ProjectName_project\ProjectName_ways.osm*
