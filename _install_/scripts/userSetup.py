# ---------------------------------- common startup site handling -----------------------------------
import os
import sys
import site
import inspect

def common_startup():
    # Add site-packages to sys.path
    package_dir = os.path.dirname(os.path.dirname(os.path.dirname(inspect.getfile(inspect.currentframe())))) # my god
    
    if package_dir not in sys.path:
        site.addsitedir(package_dir)

common_startup()



