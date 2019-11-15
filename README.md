# ISAAC Workshop III

Installation, preparation and execution stuff:

-   Setup virtualenv

    virtualenv -p python3 venv
    
    source venv/bin/activate

-   Install needed stuff using requirements.txt to virtualenv

    python -m pip install -r requirements.txt

ISAAC Standalone:
-   Edit src/isaac_standalone/config.py:
    Insert the number of agents, number of containers, and the negotiations with its corresponding targets and dates
-   Start src/isaac_standalone/isaac.py
    you can find the results as a hdf5 file 'results.hdf5' in the folder results
-   Details regarding the simulation can be found in the corresponding log file isaac_standalone/isaac_standalone.log 

ISAAC-mosaik:
-   For the mosaik coupling, you need to first got to the top folder of the project and

    python setup.py install
    
-   Now install needed stuff. In src/isaac_mosaik/ execute 

    pip install -r isaac_mosaik_requirements.txt
    
-   Now you can start src/isaac_mosaik/scenario.py and ISAAC will run within mosaik, coupled with an example simulator. 
The coupling consists of a simple exchange of schedules. No stepping of units is performed.
-   In scenario.py, settings can be changed
-   Results can be found in the results folder. The log file can be found in src/isaac_mosaik/isaac.log and src/isaac_mosaik/exampleDER.log

For a quick inspection of any results:

	python analyze_result.py

-   In the result folder you will find one pdf file 'results.pdf' with four plots per negotiation


Using the schenerator:
-   install a java runtime environment if you haven't (oracle, no jdk!):
    e.g. from http://www.oracle.com/technetwork/java/javase/downloads/jre8-downloads-2133155.html

    java -jar <path to isaac-ws2017>/schenerator/schenerator-0.0.3.jar

-   import a schedule from /data/DER_schedules, edit it and export again
-   important: the header of the new file must be correct regarding the number of schedules
-   if you restart ISAAC the new schedule(s) will be included
