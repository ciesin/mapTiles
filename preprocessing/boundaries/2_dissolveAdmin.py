import arcpy
from arcpy import env
import os
import re
import json
from datetime import datetime

def load_schema_report(schema_report_path):
    """
    Load an ESRI schema report JSON file and extract field information.
    
    Parameters:
    schema_report_path (str): Path to the ESRI schema report JSON file
    
    Returns:
    dict: Schema information with field mappings and hierarchy
    """
    if not os.path.exists(schema_report_path):
        print(f"Warning: Schema report not found at {schema_report_path}")
        return None
    
    try:
        with open(schema_report_path, 'r', encoding='utf-8') as f:
            schema_data = json.load(f)
        
        print(f"Loaded schema report: {schema_report_path}")
        
        # Extract field information from the first dataset (assuming single feature class)
        if 'datasets' in schema_data and len(schema_data['datasets']) > 0:
            dataset = schema_data['datasets'][0]
            field_array = dataset.get('fields', {}).get('fieldArray', [])
            
            schema_info = {
                'feature_class_name': dataset.get('name', ''),
                'fields': {},
                'admin_fields': [],
                'geometry_fields': [],
                'metadata_fields': []
            }
            
            # Categorize fields based on administrative hierarchy and data types
            admin_hierarchy_names = ['iso3', 'province', 'antenne', 
                                   'zonesante', 'airesante']
            
            for field in field_array:
                field_name = field['name']
                field_type = field['type']
                
                schema_info['fields'][field_name] = {
                    'type': field_type,
                    'length': field.get('length', 0),
                    'precision': field.get('precision', 0),
                    'scale': field.get('scale', 0),
                    'isNullable': field.get('isNullable', True),
                    'aliasName': field.get('aliasName', field_name)
                }
                
                # Categorize fields
                if field_name.lower() in [name.lower() for name in admin_hierarchy_names]:
                    schema_info['admin_fields'].append(field_name)
                elif field_type == 'esriFieldTypeGeometry':
                    schema_info['geometry_fields'].append(field_name)
                elif field_name.lower() in ['date', 'source_acronym', 'edit_par', 'grid3id', 'sourceid']:
                    schema_info['metadata_fields'].append(field_name)
            
            print(f"Schema loaded with {len(schema_info['fields'])} fields:")
            print(f"  Admin fields: {schema_info['admin_fields']}")
            print(f"  Metadata fields: {schema_info['metadata_fields']}")
            
            return schema_info
            
    except Exception as e:
        print(f"Error loading schema report: {e}")
        return None

def build_field_mapping_with_schema(input_fc, admin_fields, schema_info=None):
    """
    Build comprehensive field mapping for dissolve operation using schema information.
    
    Parameters:
    input_fc (str): Path to input feature class
    admin_fields (list): List of administrative field names for hierarchy
    schema_info (dict): Schema information from ESRI schema report
    
    Returns:
    list: Statistics fields mapping for dissolve operation
    """
    statistics_fields = []
    existing_fields = [f.name for f in arcpy.ListFields(input_fc)]
    geometry_field_names = set(["Shape", "Shape_Length", "Shape_Area"])
    if schema_info:
        # Use schema information to preserve all relevant fields
        print("Using schema report to build comprehensive field mapping...")
        
        # Map administrative hierarchy fields
        for admin_field in schema_info.get('admin_fields', []):
            if admin_field in existing_fields and admin_field not in geometry_field_names:
                statistics_fields.append([admin_field, "FIRST"])
                print(f"  Preserving admin field: {admin_field}")
        
        # Map metadata fields
        for metadata_field in schema_info.get('metadata_fields', []):
            if metadata_field in existing_fields and metadata_field not in geometry_field_names:
                statistics_fields.append([metadata_field, "FIRST"])
                print(f"  Preserving metadata field: {metadata_field}")
        
        # Do NOT add numeric fields at all
    else:
        # Fallback to original logic if no schema provided
        print("No schema report provided, using default field mapping...")
        
        # Preserve specified admin fields
        for admin_field in admin_fields:
            if admin_field in existing_fields and admin_field not in geometry_field_names:
                statistics_fields.append([admin_field, "FIRST"])
        
        # Do NOT add numeric fields at all
    return statistics_fields

def get_admin_level_fields(admin_fields, current_level_index, schema_info=None):
    """
    Get all administrative fields up to and including the current level,
    plus any parent administrative information that should be preserved.
    
    Parameters:
    admin_fields (list): Base administrative field names
    current_level_index (int): Index of current admin level (0-based)
    schema_info (dict): Schema information for enhanced field mapping
    
    Returns:
    list: Fields to preserve for this administrative level
    """
    # Always include admin fields up to current level
    level_fields = admin_fields[:current_level_index + 1]
    
    # CRITICAL: Add all parent pagename fields to preserve them in child dissolved feature classes
    # Children should contain all their parents' pagename fields
    # For example, zonesante dissolve should preserve pagename_antenne and pagename_province
    parent_pagename_fields = []
    for j in range(current_level_index):
        parent_pagename_field = f"pagename_{admin_fields[j]}"
        parent_pagename_fields.append(parent_pagename_field)
    
    level_fields.extend(parent_pagename_fields)
    
    if schema_info:
        # Add corresponding UID fields and other related fields
        admin_mapping = {
            'province': ['pays', 'iso3', 'prov_uid'],
            'antenne': ['pays', 'iso3', 'province', 'prov_uid'],
            'zonesante': ['pays', 'iso3', 'province', 'prov_uid', 'antenne', 'zs_uid'],
            'airesante': ['pays', 'iso3', 'province', 'prov_uid', 'antenne', 'zonesante', 'zs_uid', 'as_uid', 'asnom_alt']
        }
        
        current_admin = admin_fields[current_level_index]
        if current_admin in admin_mapping:
            additional_fields = admin_mapping[current_admin]
            for field in additional_fields:
                if field not in level_fields and field in schema_info.get('admin_fields', []):
                    level_fields.append(field)
    
    return level_fields

def perform_dissolve(input_fc, admin_fields, data_path, output_path, YYYYMMDD=None, schema_report_path=None, use_schema=True):
    """
    Dissolve feature class by pagename fields with optional schema preservation.
    
    Parameters:
    input_fc (str): Path to the input feature class with pagename fields
    admin_fields (list): List of administrative field names
    data_path (str): Base data directory path
    output_path (str): Relative path to processed/output geodatabase
    YYYYMMDD (str): Date string for output naming (optional, will use current date if None)
    schema_report_path (str): Path to ESRI schema report JSON file (optional)
    use_schema (bool): Whether to use schema report for field preservation (default True)
    
    Returns:
    list: List of dissolved output feature class paths created
    """
    if YYYYMMDD is None:
        YYYYMMDD = datetime.now().strftime("%Y%m%d")
    
    # Set environment settings
    target_gdb = os.path.join(data_path, output_path.strip("\\"))
    env.overwriteOutput = True

    print(f"Target geodatabase: {target_gdb}")
    print(f"Processing input: {input_fc}")
    
    # Load schema information if provided
    schema_info = None
    if use_schema and schema_report_path:
        schema_info = load_schema_report(schema_report_path)
        if schema_info:
            print("Schema-based field preservation enabled")
        else:
            print("Schema report could not be loaded, using default field mapping")
    elif not use_schema:
        print("Schema-based field preservation disabled by user")
    else:
        print("No schema report path provided, using default field mapping")

    # Generate pagename fields based on admin_fields
    pagename_fields = [f"pagename_{admin}" for admin in admin_fields]

    # Extract the base feature class name for output naming
    input_basename = os.path.basename(input_fc)
    # Remove any _pagename_... suffix for base name
    if "_pagename_" in input_basename:
        base_name = input_basename.split("_pagename_")[0]
    else:
        base_name = input_basename

    # Parse version string (e.g., v5_0) from base_name without preceding underscore
    version_match = re.search(r'v\d+_\d+', base_name)
    version_str = version_match.group(0) if version_match else ''

    dissolved_outputs = []

    # Get original field aliases for later use
    input_field_aliases = {f.name: f.aliasName for f in arcpy.ListFields(input_fc)}

    # Process each pagename field
    for i, pagename_field in enumerate(pagename_fields):
        current_admin = admin_fields[i]
        output_base = f"GRID3_COD_{current_admin}_nested_{version_str}" if version_str else f"GRID3_COD_{current_admin}_nested"
        dissolve_output = f"{target_gdb}\\{output_base}_pagename_{YYYYMMDD}"
        print(f"\nProcessing {pagename_field} ({i+1}/{len(pagename_fields)})")
        print(f"  Output: {os.path.basename(dissolve_output)}")
        
        # NOTE: Even for the lowest level (airesante), we perform a dissolve operation
        # Although geometrically redundant, this ensures consistent schema and field 
        # structure across all admin levels, which is critical for downstream processing
        # (especially for page orientation calculation and map series generation)
        
        # Build comprehensive field mapping
        if schema_info:
            # Get administrative fields for this level using schema information
            admin_level_fields = get_admin_level_fields(admin_fields, i, schema_info)
            # Build complete statistics field mapping
            statistics_fields = []
            # Add administrative fields for current level
            for field in admin_level_fields:
                existing_fields = [f.name for f in arcpy.ListFields(input_fc)]
                if field in existing_fields:
                    statistics_fields.append([field, "FIRST"])
            # Add other fields based on schema, but skip geometry fields
            all_mapped_fields = build_field_mapping_with_schema(input_fc, admin_fields, schema_info)
            existing_mapped = [sf[0] for sf in statistics_fields]
            for field_mapping in all_mapped_fields:
                # Exclude geometry fields
                if field_mapping[0] not in existing_mapped and field_mapping[0] not in schema_info.get('geometry_fields', []):
                    statistics_fields.append(field_mapping)
        else:
            statistics_fields = [
                [admin_fields[j], "FIRST"] for j in range(i+1)
            ]
            
            # CRITICAL: Add all parent pagename fields to preserve them in child dissolves
            # This ensures children contain their parents' pagename fields
            # For example, zonesante dissolve preserves pagename_antenne and pagename_province
            for j in range(i):
                parent_pagename_field = f"pagename_{admin_fields[j]}"
                statistics_fields.append([parent_pagename_field, "FIRST"])
        # Print parent pagename fields being preserved for transparency
        preserved_parent_pagenames = [sf[0] for sf in statistics_fields if sf[0].startswith('pagename_') and sf[0] != pagename_field]
        if preserved_parent_pagenames:
            print(f"  Preserving parent pagename fields: {preserved_parent_pagenames}")
        print(f"  Preserving {len(statistics_fields)} total fields")
        print(f"  Dissolve field: {pagename_field}")
        try:
            arcpy.management.Dissolve(
                input_fc,
                dissolve_output,
                pagename_field,
                statistics_fields=statistics_fields,
                multi_part="SINGLE_PART"
            )
            # Rename fields to remove FIRST_/SUM_ prefixes and set aliases
            output_fields = arcpy.ListFields(dissolve_output)
            output_field_names = [f.name for f in output_fields]
            geometry_field_names = set(["Shape", "Shape_Length", "Shape_Area"])
            for stat_field, stat_type in statistics_fields:
                stat_fieldname = f"{stat_type}_{stat_field}" if stat_type != "" else stat_field
                # Only attempt if the field exists in output and not a geometry field
                if (stat_fieldname in output_field_names and
                    stat_field not in geometry_field_names and
                    stat_field not in output_field_names):
                    try:
                        # Set alias to match input field
                        alias = input_field_aliases.get(stat_field, stat_field)
                        arcpy.management.AlterField(dissolve_output, stat_fieldname, stat_field, alias)
                    except Exception as e:
                        print(f"Warning: Could not rename field {stat_fieldname} to {stat_field}: {str(e)}")
            if arcpy.Exists(dissolve_output):
                print(f"Dissolved output created: {dissolve_output}")
                dissolved_outputs.append(dissolve_output)
            else:
                print(f"Failed to create dissolved output: {dissolve_output}")
        except Exception as e:
            print(f"Error processing {pagename_field}: {str(e)}")
    print(f"\nDissolve processing complete. Created {len(dissolved_outputs)} dissolved feature classes.")
    return dissolved_outputs

if __name__ == "__main__":
    # Input paths
    data_path = r"C:\Users\mjh2241\Documents\ArcGIS\Projects\CIESIN_STAC\data\admin_v8_dissolves.gdb"
    output_path = r"C:\Users\mjh2241\Documents\ArcGIS\Projects\CIESIN_STAC\data\admin_v8_dissolves.gdb"
    target_gdb = output_path
    YYYYMMDD = datetime.now().strftime("%Y%m%d")
    # admin_fields = ["province", "antenne", "zonesante", "airesante"]
    admin_fields = ["province", "antenne", "zonesante"]
    indexFeatures = "GRID3_COD_health_zones_v8_0_pagename_20260408"
    # Construct full feature class path as expected by arcpy (gdb path + feature class name)
    input_fc = os.path.join(data_path, indexFeatures)
    print(input_fc)
    
    # Schema report configuration (optional)
    # Set to None to disable schema-based field preservation
    schema_report_path = r"D:\mheaton\Cartography\RDC_EAF\data\20250923\scratch\airesante_v7_schemareport.json"
    use_schema = True  # Set to False to disable schema-based preservation
    
    if arcpy.Exists(input_fc):
        dissolved_outputs = perform_dissolve(
            input_fc,
            admin_fields,
            data_path,
            output_path,
            YYYYMMDD,
            schema_report_path=schema_report_path,
            use_schema=use_schema
        )
        print(f"\nProcessing complete. Created {len(dissolved_outputs)} dissolved feature classes.")
        
        if schema_report_path and use_schema:
            print(f"\nSchema report used: {schema_report_path}")
            print("Administrative hierarchy and metadata fields preserved according to schema.")
    else:
        print(f"Input feature class not found: {input_fc}")
        print("Please run 2_addPageName.py first to create the input feature class.")
