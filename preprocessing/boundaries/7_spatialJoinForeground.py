import arcpy
from arcpy import env
import os
from datetime import datetime

def perform_spatial_join(input_gdb, index_feature_class, pattern="*", exclude=None, suffix="_pagename", output_gdb=None):
    """
    Perform spatial join between point feature classes and an index polygon feature class.
    
    Parameters:
    input_gdb (str): Path to the input geodatabase
    index_feature_class (str): Name of the index polygon feature class (without path)
    pattern (str): Pattern to match point feature classes (default: "*" for all)
    exclude (str): String to exclude from feature class names (optional, default: None)
    suffix (str): Suffix to add to output feature class names
    output_gdb (str): Path to the output geodatabase (optional, defaults to input_gdb)
    
    Returns:
    list: List of output feature class names created
    """
    
    # Set destination geodatabase (default to input if not specified)
    if output_gdb is None:
        output_gdb = input_gdb
    
    # Set environment settings
    env.workspace = input_gdb
    env.overwriteOutput = True
    
    print(f"Processing geodatabase: {input_gdb}")
    print(f"Output geodatabase: {output_gdb}")
    print(f"Index feature class: {index_feature_class}")
    if exclude:
        print(f"Excluding feature classes containing: {exclude}")
    
    # Check if output geodatabase exists, create if it doesn't
    if not arcpy.Exists(output_gdb):
        print(f"Creating output geodatabase: {output_gdb}")
        gdb_path, gdb_name = os.path.split(output_gdb)
        arcpy.management.CreateFileGDB(gdb_path, gdb_name)
    
    # Check if index feature class exists
    if not arcpy.Exists(index_feature_class):
        print(f"Error: Index feature class '{index_feature_class}' not found in geodatabase")
        return []
    
    # Verify index feature class is polygon
    desc = arcpy.Describe(index_feature_class)
    if desc.shapeType != "Polygon":
        print(f"Error: Index feature class '{index_feature_class}' is not a polygon (Type: {desc.shapeType})")
        return []
    
    # Find all point feature classes matching the pattern
    all_fcs = arcpy.ListFeatureClasses(pattern, "Point")
    
    if not all_fcs:
        print(f"No point feature classes found matching pattern: {pattern}")
        return []
    
    # Filter out feature classes containing the exclude string
    if exclude:
        initial_count = len(all_fcs)
        all_fcs = [fc for fc in all_fcs if exclude not in fc]
        excluded_count = initial_count - len(all_fcs)
        if excluded_count > 0:
            print(f"Excluded {excluded_count} feature classes containing '{exclude}'")
    
    if not all_fcs:
        print(f"No point feature classes remaining after applying pattern '{pattern}' and exclude '{exclude}'")
        return []
    
    print(f"Found {len(all_fcs)} point feature classes to examine")
    
    output_features = []
    processed_count = 0
    
    for fc in all_fcs:
        # Skip if it's the same as the index feature class
        if fc == index_feature_class:
            print(f"Skipping: {fc} (matches index feature class)")
            continue
            
        print(f"Processing: {fc}")
        
        try:
            # Check if it's a point feature class
            desc = arcpy.Describe(fc)
            if desc.shapeType != "Point":
                print(f"  Skipping - not a point (Type: {desc.shapeType})")
                continue
            
            processed_count += 1
            
            # Generate output feature class name and full path
            output_fc_name = f"{fc}{suffix}"
            output_fc_path = os.path.join(output_gdb, output_fc_name)
            
            print(f"  Performing spatial join: {fc} -> {output_fc_name}")
            
            # Perform spatial join with KEEP_ALL to retain all points
            arcpy.analysis.SpatialJoin(
                target_features=fc,
                join_features=index_feature_class,
                out_feature_class=output_fc_path,
                join_operation="JOIN_ONE_TO_ONE",
                join_type="KEEP_ALL",
                match_option="INTERSECT"
            )

            # Field mapping: update pagename_{admin} fields only for intersected points
            # Get join fields (from index_feature_class)
            join_fields = [f.name for f in arcpy.ListFields(index_feature_class) if f.name.lower().startswith('pagename_')]
            # Get output fields
            output_fields = [f.name for f in arcpy.ListFields(output_fc_path)]
            # Find matching pagename fields in output
            matching_fields = [f for f in join_fields if f in output_fields]

            # Use UpdateCursor to update only intersected points
            with arcpy.da.UpdateCursor(output_fc_path, ['TARGET_FID'] + matching_fields) as cursor:
                for row in cursor:
                    target_fid = row[0]
                    # If TARGET_FID is not None, this point intersected a polygon
                    if target_fid is not None:
                        # For each matching field, if join value is not None, update
                        for i, field in enumerate(matching_fields, start=1):
                            if row[i] is not None:
                                row[i] = row[i]  # Already set by join
                            # else: leave as is (preserve existing value)
                        cursor.updateRow(row)
                    # If TARGET_FID is None, do not update (preserve original values)
            
            if arcpy.Exists(output_fc_path):
                print(f"  Successfully created: {output_fc_name}")
                output_features.append(output_fc_name)
            else:
                print(f"  Failed to create: {output_fc_name}")
                
        except Exception as e:
            print(f"  Error processing {fc}: {str(e)}")
    
    print(f"\nSpatial join complete:")
    print(f"  Examined {len(all_fcs)} feature classes")
    print(f"  Processed {processed_count} point feature classes")
    print(f"  Successfully created {len(output_features)} output feature classes")
    
    return output_features

if __name__ == "__main__":
    # Example usage - modify these paths as needed
    input_gdb = r"D:\mheaton\Cartography\RDC_EAF\data\20251208\scratch\boundaryJoins_20251209.gdb"
    index_feature_class = "GRID3_COD_airesante_nested_v7_0_pagename_20251209"  # fc in input gdb to join against
    
    # Optional: specify a pattern to match only certain point feature classes
    # Examples:
    # pattern = "*health*"      # Only feature classes with "health" in the name
    # pattern = "*facility*"    # Only feature classes with "facility" in the name
    # pattern = "*"             # All point feature classes (default)
    
    # pattern = "TU_SU_*"  # match fc pattern for point feature classes
    pattern = "*"  # match all point feature classes
    
    # Optional: specify a string to exclude from feature classes
    # Examples:
    # exclude = "temp"          # Exclude feature classes containing "temp"
    # exclude = "_backup"       # Exclude feature classes containing "_backup"
    # exclude = None            # Don't exclude anything (default)
    
    exclude = None  # Don't exclude any feature classes
    
    # Optional: specify a different output geodatabase
    # Examples:
    output_gdb = r"D:\mheaton\Cartography\RDC_EAF\data\20251209\processed\processed.gdb"  # Different geodatabase for outputs
    # output_gdb = None                      # Use input geodatabase (default)
    
    output_gdb = None  # Use input geodatabase for outputs
    
    print(f"Performing spatial joins in: {input_gdb}")
    print(f"Index feature class: {index_feature_class}")
    print(f"Point feature class pattern: {pattern}")
    if exclude:
        print(f"Excluding feature classes containing: {exclude}")
    if output_gdb:
        print(f"Output will be saved to: {output_gdb}")
    else:
        print(f"Output will be saved to: {input_gdb} (same as input)")
    
    # Perform spatial joins for all matching point feature classes
    output_features = perform_spatial_join(input_gdb, index_feature_class, pattern, exclude, "_pagename", output_gdb)
    
    if output_features:
        print(f"\nSpatial join successful! Created {len(output_features)} output feature classes:")
        for output_fc in output_features:
            print(f"  - {output_fc}")
    else:
        print("\nNo spatial joins were performed.")
        print("Check that the geodatabase path and index feature class are correct,")
        print("and that there are point feature classes matching the pattern.")
