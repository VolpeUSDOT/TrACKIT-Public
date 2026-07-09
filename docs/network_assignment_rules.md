# Network Attribute Assignment Rules

## OSM Attribute Assignment Rules
The following rules are used during the initial data download and network generation. The tool scans OSM tags to determine if a mode is allowed,

### Access & Permissions
| *Highway* | *Vehicle* | *Truck*^ | *Pedestrian* | *Low Stress Pedestrian* | *Bicycle* | *Low Stress Bicycle* |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| motorway | all | all | never* | never* | never* | never* |
| trunk | all | all | never* | never* | if bike lane* | if separated bike lane only* |
| primary | all | all | all | never* | all | if separated bike lane only* |
| secondary | all | all | all | never* | all | if separated bike lane only* |
| tertiary | all | all | all | never* | all | if bike lane* |
| residential | all | never | all | all | all | all |
| service | never | never | never | never | never | never |
| unclassified | all | all | all | all | all | if bike lane* |
| living street | all | never | all | all | all | all |
| cycleway | never | never | all | all | all | all |
| track | never | never | all | all | all | all |
| footway | never | never | all | all | all | all |
| corridor | never | never | all | all | never | never |
| steps | never | never | all | all | all | never |
| path | never | never | all | all | all | all |

### Default Speeds (mph)
| *Highway* | *Vehicle Spd* | *Truck Spd*^ | *Pedestrian Spd* | *Bicycle Spd* | *Low Stress Bicycle Spd* |
| :--- | :---: | :---: | :---: | :---: | :---: |
| motorway | 55 | 52.25 | 3 | 10* | 10* |
| trunk | 35 | 33.25 | 3 | 10* | 10* |
| primary | 25 | 23.75 | 3 | 10 | 10* |
| secondary | 25 | 23.75 | 3 | 10 | 10* |
| tertiary | 25 | 15 | 3 | 10 | 10* |
| residential | 20 | 0 | 3 | 10 | 10 |
| service | 0 | 0 | 3 | 10 | 10 |
| unclassified | 25 | 15 | 3 | 10 | 10* |
| living street | 10 | 0 | 3 | 10 | 10 |
| cycleway | 0 | 0 | 3 | 10 | 10 |
| track | 0 | 0 | 3 | 10 | 10 |
| footway | 0 | 0 | 3 | 3 | 3 |
| corridor | 0 | 0 | 3 | 3 | 3 |
| steps | 0 | 0 | 3 | 3 | 3 |
| path | 0 | 0 | 3 | 3 | 3 |

> **Condition Notes:**

> * **\*** **Pedestrian & Bike Inclusion:** These links are included if there are pedestrian infrastructure tags associated with the link. For the bicycle network, these links are set at a speed limit of 3 if they were not already included.

> * **^** **Truck Routing:** rucks are allowed on highway types marked “all” assuming they meet the conditions listed in [Freight Truck Assignment Rules](freight-truck-assignment-rules) below. These rules also explain how truck speeds are assigned.

---

## Manual Edit Integration Defaults (Auto-Population)
When you manually draw or copy links into a scenario and leave mode or speed fields blank, the tool applies the conservative defaults below based on the “highway” field during [Step 2C: Integrate Scenario](step2.md#step-2c-integrate-manual-edits-into-scenario-network). For default speeds, the tool applies the speeds listed in the [table below](#defaults-for-auto-population). Note that this this "auto-population" of blank fields will only work if there is a known value in the "highway" field.

### Defaults for Auto-Population
| *Highway* | *Vehicle* | *Truck* | *Pedestrian* | *Low Stress Pedestrian* | *Bicycle* | *Low Stress Bicycle* |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| motorway | Yes | Yes | No | No | No | No |
| trunk | Yes | Yes | No | No | No | No |
| primary | Yes | Yes | Yes | No | Yes | No |
| secondary | Yes | Yes | Yes | No | Yes | No |
| tertiary | Yes | Yes | Yes | Yes | Yes | No |
| residential | Yes | No | Yes | Yes | Yes | Yes |
| service | No | No | No | No | No | No |
| unclassified | Yes | Yes | Yes | Yes | Yes | Yes |
| living street | Yes | No | Yes | Yes | Yes | Yes |
| cycleway | No | No | Yes | Yes | Yes | Yes |
| track | No | No | Yes | Yes | Yes | Yes |
| footway | No | No | Yes | Yes | Yes | Yes |
| corridor | No | No | Yes | Yes | No | No |
| steps | No | No | Yes | Yes | Yes | No |
| path | No | No | Yes | Yes | Yes | Yes |


---

## Freight Truck Assignment Rules
The truck network is built from the vehicle network but introduces specific restrictions and penalties. 

**Prohibited Links**

* Removes residential and living streets from the truck network.
* Removes links where the hgv tag is marked “no” or “discouraged”.
* Removes links where hgv is tagged as “conditional” with a subtag value containing “permit” (hinting at a permit requirement).

**Physical Restrictions**

The tool checks for a 'maxheight', 'maxweight', or 'maxwidth' tag. If values hint at no restriction (e.g., no, unsigned, etc.), the link passes. Otherwise, the link is removed if any of the following constraints apply:

* 'maxheight' is over 13’6”.
* 'maxweight' is over 80k lbs.
* 'maxwidth' is over 8’6”.

**Speed Modifications**

* **Soft Penalties:** Includes soft speed penalties (50% of normal vehicle speed) for links where the hgv tag is marked “destination,” “delivery,” or “local,” as these signal that these roads should be avoided for pass-through routing.
* **Hard-coded Limitations:** Assigns hard-coded speeds of 15 mph for any tertiary or unclassified links (to discourage their use and to reflect slower speeds when navigating these lower classification roads).
* **General Throttle:** Throttles down all typical vehicle speeds by 5%.