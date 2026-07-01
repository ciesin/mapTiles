import arcpy
from arcpy import env
import re
import os
from datetime import datetime
import unicodedata

#TODO: Resolve duplication of field names ... field mapping

# data_path = r"E:\mheaton\cartography\GRID_2025\RDC_EAF_2025\data\20250521"
input_gdb = r"C:\Users\mjh2241\Documents\ArcGIS\Projects\CIESIN_STAC\data\GRID3_COD_health_zones_v8_0.gdb"
output_gdb = r"C:\Users\mjh2241\Documents\ArcGIS\Projects\CIESIN_STAC\data\admin_v8_dissolves.gdb"

YYYYMMDD = datetime.now().strftime("%Y%m%d")

# Set environment settings
env.workspace = input_gdb
print(f"Input workspace: {env.workspace}")
env.overwriteOutput = True

# Set the target geodatabase for output feature classes
# (output_gdb is used directly below)

# Set the local variables
indexFeatures = "GRID3_COD_health_zones_v8_0"
# admin_fields = ["province", "antenne" ,"zonesante", "airesante"]
admin_fields = ["province", "antenne" ,"zonesante"]


# Create output feature class with pagename fields (copy of input to preserve original)
output_indexFeatures = f"{output_gdb}\\{indexFeatures}_pagename_{YYYYMMDD}"
arcpy.management.CopyFeatures(indexFeatures, output_indexFeatures)
print(f"Created working copy: {output_indexFeatures}")

# Dynamically generate pagename fields based on admin_fields
pagename_fields = [f"pagename_{admin}" for admin in admin_fields]

# Ensure only the dynamically named fields are created
existing_fields = [f.name for f in arcpy.ListFields(output_indexFeatures)]
for pagename_field in pagename_fields:
    if pagename_field not in existing_fields:
        arcpy.AddField_management(output_indexFeatures, pagename_field, "TEXT")

# Create pagename fields for each administrative level
for i, pagename_field in enumerate(pagename_fields):
    if i == 0:
        expression = f"!iso3! + '_' + !{admin_fields[i]}!"
    else:
        expression = "!iso3! + '_' + " + " + '_' + ".join([f'!{admin_fields[j]}!' for j in range(i+1)])
    
    arcpy.CalculateField_management(output_indexFeatures, pagename_field, expression, "PYTHON3")

# Define a function to transliterate accented characters and replace problematic characters
code_block = """
import unicodedata

def remove_non_ascii(text):
    # Transliterate accented characters to their ASCII equivalents
    # This preserves readability for French text like "Kasaï-Oriental" -> "Kasai-Oriental"
    normalized_text = unicodedata.normalize('NFD', text)
    ascii_text = ''.join(char for char in normalized_text if unicodedata.category(char) != 'Mn')
    
    # Replace spaces with hyphens
    cleaned_text = ascii_text.replace(' ', '-')
    
    # Replace forward/backslashes, apostrophes, and other problematic characters with hyphens
    cleaned_text = re.sub('[\\\\/:*?"<>|]', '-', cleaned_text)
    
    # Reduce multiple consecutive hyphens to single hyphen
    cleaned_text = re.sub('-+', '-', cleaned_text)
    
    # Remove leading/trailing hyphens
    cleaned_text = cleaned_text.strip('-')
    
    return cleaned_text
"""

# Apply the function to the 'pagename' fields
for pagename_field in pagename_fields:
    arcpy.CalculateField_management(output_indexFeatures, pagename_field, "remove_non_ascii(!{}!)".format(pagename_field), "PYTHON3", code_block)

print(f"Generated pagename fields for {len(admin_fields)} administrative levels: {', '.join(pagename_fields)}")