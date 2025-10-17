# How to navigate this project

## extract cycles
If you want to get the cycles of a project, navigate to the folder `cycle_extractor`.
Then run `.\analyze_cycles.bat ..\testProject2\`. testProject2 can be replaced with your desired project to analyze.
You will then get your cycles json in `output\cycles.json`.

Depends needs to be in the `ATD_identification` folder.
Except if you already have the depends output and just want to extract the cycles, you can just do:

`python parse_module_cycles.py ..\output\result-modules-sdsm.json-file.json ..\output\module_cycles.json`

`python parse_function_cycles.py ..\output\result-functions-sdsm.json-method.json ..\output\function_cycles.json`

`python merge_cycles.py ..\output\module_cycles.json ..\output\function_cycles.json ..\output\cycles.json`

Replace the paths with your desired paths.

## visualize cycles
Yoy can move this `output\cycles.json` file into the `ATD_visualuzation` folder. And open `ATD_graph_app.py`
In the beggining of the file it says `with open("cyclesTensorflow.json") as f:`. You can replace `cyclesTensorflow.json` with your `cycles.json`. Then just run the python file.

## Note:
I am in the very beggining of working on my master thesis, so to achieve fast prototyping a lot of the code is generated using chatGPT. That is why I created the testProject2, to be able to verify that it is working as intended. And also, when applying this on big projects like e.g. tensorflow, some of the components are very thightly connected and there is therefore a ton of cycles. So to make the cycle_extractor not run forever I made it extract at most 500 cycles per strongly connected component (SCC). A SCC is a set of nodes where every node can reach every other node. I also made the cycle_extractor try to avoid including modules used for testing. So files that include "test" in their name is ignored. If you do not want this behaviour, you can simply comment it out in `parse_module_cycles.py` (see the function `is_test_node()`).
