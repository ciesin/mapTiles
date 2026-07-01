"""
Calculate page orientation (PORTRAIT/LANDSCAPE) for nested administrative boundary polygons.

This script can process either:
1. A single feature class
2. All eligible feature classes in a geodatabase (with optional pattern matching and exclusions)

Usage:
    Single feature class:
        python 4_calculatePageOrientation.py "path/to/feature_class"
    
    Entire geodatabase:
        python 4_calculatePageOrientation.py "path/to/geodatabase.gdb"
    
    Geodatabase with pattern:
        python 4_calculatePageOrientation.py "path/to/geodatabase.gdb" "*nested*"
    
    Geodatabase with pattern and exclusion:
        python 4_calculatePageOrientation.py "path/to/geodatabase.gdb" "*nested*" "temp"

Parameters:
    arg1: Path to feature class or geodatabase (required)
    arg2: Pattern to match feature classes, e.g., "*nested*", "*province*" (optional, default: "*")
    arg3: String to exclude from feature class names, e.g., "temp", "_backup" (optional)

The script automatically:
- Detects the admin level (province/antenne/zonesante/airesante) from the feature class name
- Uses the corresponding pagename field for grouping
- Creates MBRs and calculates orientation
- Includes diagnostic output to identify potential issues
"""

import arcpy
from arcpy import env
import sys
import os

env.overwriteOutput = True

# Function to determine the active input field based on feature class name
def get_active_field(feature_class_path):
    base_name = arcpy.Describe(feature_class_path).baseName
    if "_airesante_" in base_name:
        return "pagename_airesante"
    elif "_zonesante_" in base_name:
        return "pagename_zonesante"
    elif "_province_" in base_name:
        return "pagename_province"
    elif "_antenne_" in base_name:
        return "pagename_antenne"
    else:
        raise ValueError(f"Unable to determine field from feature class name: {base_name}")

def calculate_page_orientation(input_feature_class, temp_mbr_fc=None):
    """
    Calculate page orientation (PORTRAIT/LANDSCAPE) for polygons based on their minimum bounding rectangle.
    
    Args:
        input_feature_class: Path to input polygon feature class
        temp_mbr_fc: Optional path for temporary MBR feature class (will be deleted)
    """
    
    # Set up temporary MBR feature class name if not provided
    if not temp_mbr_fc:
        workspace = os.path.dirname(input_feature_class)
        temp_mbr_fc = os.path.join(workspace, "temp_mbr_orientation")
    
    try:
        # Step 1: Determine the grouping field
        active_field = get_active_field(input_feature_class)
        print(f"Using field for MBR grouping: {active_field}")
        
        # DIAGNOSTIC: Check for NULL or empty values in the grouping field
        null_count = 0
        total_count = 0
        unique_values = set()
        with arcpy.da.SearchCursor(input_feature_class, [active_field]) as cursor:
            for row in cursor:
                total_count += 1
                if row[0] is None or row[0] == "":
                    null_count += 1
                else:
                    unique_values.add(row[0])
        
        print(f"\nDIAGNOSTIC - Input Feature Class Analysis:")
        print(f"  Total features: {total_count}")
        print(f"  Null/empty {active_field}: {null_count}")
        print(f"  Unique {active_field} values: {len(unique_values)}")
        
        if null_count > 0:
            print(f"  WARNING: {null_count} features have NULL/empty {active_field} - these will fail to join!")
        
        # Step 2: Create minimum bounding rectangles grouped by the active field
        print("\nCreating minimum bounding rectangles...")
        arcpy.MinimumBoundingGeometry_management(
            input_feature_class, 
            temp_mbr_fc, 
            "RECTANGLE_BY_AREA", 
            "LIST", 
            active_field, 
            "MBG_FIELDS"
        )
        
        # DIAGNOSTIC: Check MBR output
        mbr_count = int(arcpy.GetCount_management(temp_mbr_fc).getOutput(0))
        print(f"  Created {mbr_count} MBR features")
        print(f"  Expected {len(unique_values)} unique MBRs (one per unique {active_field})")
        
        if mbr_count != len(unique_values):
            print(f"  WARNING: MBR count mismatch! Expected {len(unique_values)}, got {mbr_count}")
        
        # Step 3: Find the orientation field (it might have different names)
        print("Identifying orientation field...")
        mbr_fields = [f.name for f in arcpy.ListFields(temp_mbr_fc)]
        print(f"Available MBR fields: {mbr_fields}")
        
        # Look for orientation field with various possible names
        orientation_field = None
        possible_names = ["MBR_Orientation", "Orientation", "ORIENTATION", "MBROrient", "MBGORIENT"]
        for field_name in possible_names:
            if field_name in mbr_fields:
                orientation_field = field_name
                break
        
        # If still not found, look for any field containing "orient" or "angle"
        if not orientation_field:
            for field_name in mbr_fields:
                if "orient" in field_name.lower() or "angle" in field_name.lower():
                    orientation_field = field_name
                    break
        
        if not orientation_field:
            raise ValueError(f"Could not find orientation field in MBR feature class. Available fields: {mbr_fields}")
        
        print(f"Using orientation field: {orientation_field}")
        
        # Step 4: Add orientation field to MBR feature class
        print("Calculating page orientation...")
        arcpy.AddField_management(temp_mbr_fc, "pageOrientation", "TEXT", field_length=10)
        
        # Step 5: Calculate orientation based on the found orientation angle field
        # MBR orientation represents the angle of the long axis from horizontal
        # For portrait: long axis should be more vertical (closer to 90 degrees)
        # For landscape: long axis should be more horizontal (closer to 0 or 180 degrees)
        
        orientation_expression = """
def get_orientation(angle):
    # Handle None/null values
    if angle is None:
        return "LANDSCAPE"  # Default to landscape if no angle
    
    # PORTRAIT: angle < 45 OR angle >= 135
    # LANDSCAPE: angle >= 45 AND angle < 135
    angle_val = float(angle)
    
    if angle_val < 45 or angle_val >= 135:
        return "PORTRAIT"
    else:
        return "LANDSCAPE"
"""
        
        arcpy.CalculateField_management(
            temp_mbr_fc, 
            "pageOrientation", 
            f"get_orientation(!{orientation_field}!)", 
            "PYTHON3",
            orientation_expression
        )
        
        # Step 6: Join orientation back to original feature class
        print("Joining orientation back to original feature class...")
        
        # Check if pageOrientation field already exists, delete if so
        existing_fields = [f.name for f in arcpy.ListFields(input_feature_class)]
        if "pageOrientation" in existing_fields:
            print("Removing existing pageOrientation field...")
            try:
                arcpy.DeleteField_management(input_feature_class, "pageOrientation")
            except Exception as e:
                print(f"Could not delete existing pageOrientation field: {e}")
                raise ValueError("Cannot modify feature class - it may be open in another application. Please close ArcGIS Pro or any other applications using this data.")
        
        # Add the field to input feature class
        try:
            arcpy.AddField_management(input_feature_class, "pageOrientation", "TEXT", field_length=10)
        except Exception as e:
            print(f"Could not add pageOrientation field: {e}")
            raise ValueError("Cannot modify feature class - it may be open in another application. Please close ArcGIS Pro or any other applications using this data.")
        
        # Create feature layers for joining
        arcpy.MakeFeatureLayer_management(input_feature_class, "input_layer")
        arcpy.MakeFeatureLayer_management(temp_mbr_fc, "mbr_layer")
        
        # DIAGNOSTIC: Count features before join
        input_count_before = int(arcpy.GetCount_management("input_layer").getOutput(0))
        print(f"\nDIAGNOSTIC - Pre-join counts:")
        print(f"  Input layer features: {input_count_before}")
        print(f"  MBR layer features: {mbr_count}")
        
        # Perform join and calculate field
        arcpy.AddJoin_management("input_layer", active_field, "mbr_layer", active_field, "KEEP_COMMON")
        
        # DIAGNOSTIC: Count features after join
        input_count_after = int(arcpy.GetCount_management("input_layer").getOutput(0))
        print(f"\nDIAGNOSTIC - Post-join counts:")
        print(f"  Joined layer features: {input_count_after}")
        print(f"  Features lost in join: {input_count_before - input_count_after}")
        
        if input_count_after < input_count_before:
            print(f"  WARNING: {input_count_before - input_count_after} features will not get orientation values!")
            print(f"  This is likely due to NULL {active_field} values or join failures.")
        
        # Get the full field name after join
        temp_mbr_basename = arcpy.Describe(temp_mbr_fc).baseName
        joined_orientation_field = f"{temp_mbr_basename}.pageOrientation"
        
        # Calculate the field
        arcpy.CalculateField_management(
            "input_layer", 
            "pageOrientation", 
            f"!{joined_orientation_field}!", 
            "PYTHON3"
        )
        
        # Remove join and clean up layers
        arcpy.RemoveJoin_management("input_layer", temp_mbr_basename)
        arcpy.Delete_management("input_layer")
        arcpy.Delete_management("mbr_layer")
        
        # Count results
        portrait_count = 0
        landscape_count = 0
        null_orientation_count = 0
        
        with arcpy.da.SearchCursor(input_feature_class, ["pageOrientation"]) as cursor:
            for row in cursor:
                if row[0] == "PORTRAIT":
                    portrait_count += 1
                elif row[0] == "LANDSCAPE":
                    landscape_count += 1
                else:
                    null_orientation_count += 1
        
        total_count = int(arcpy.GetCount_management(input_feature_class).getOutput(0))
        
        print(f"\n{'='*60}")
        print(f"Page orientation calculation complete:")
        print(f"  PORTRAIT: {portrait_count}")
        print(f"  LANDSCAPE: {landscape_count}")
        print(f"  NULL/Missing: {null_orientation_count}")
        print(f"  Total: {total_count}")
        print(f"{'='*60}")
        
        if null_orientation_count > 0:
            print(f"\n⚠️  CRITICAL: {null_orientation_count} features have no orientation value!")
            print(f"   This is likely due to NULL/empty {active_field} values that couldn't be joined.")
            print(f"   These features will cause problems in map series generation.")
        
    except Exception as e:
        print(f"Error in calculate_page_orientation: {str(e)}")
        raise
    finally:
        # Clean up temporary MBR feature class
        if arcpy.Exists(temp_mbr_fc):
            arcpy.Delete_management(temp_mbr_fc)
            print("Cleaned up temporary MBR feature class")

def process_geodatabase(input_gdb, pattern="*", exclude=None):
    """
    Process all polygon feature classes in a geodatabase that match the pattern.
    
    Parameters:
    input_gdb (str): Path to the input geodatabase
    pattern (str): Pattern to match feature classes (default: "*" for all)
    exclude (str): String to exclude from feature class names (optional)
    
    Returns:
    tuple: (successful_count, failed_count, total_count)
    """
    
    # Set environment settings
    env.workspace = input_gdb
    
    print(f"Processing geodatabase: {input_gdb}")
    print(f"Pattern: {pattern}")
    if exclude:
        print(f"Excluding feature classes containing: {exclude}")
    
    # Find all polygon feature classes matching the pattern
    all_fcs = arcpy.ListFeatureClasses(pattern, "Polygon")
    
    if not all_fcs:
        print(f"No polygon feature classes found matching pattern: {pattern}")
        return (0, 0, 0)
    
    # Filter out feature classes containing the exclude string
    if exclude:
        initial_count = len(all_fcs)
        all_fcs = [fc for fc in all_fcs if exclude not in fc]
        excluded_count = initial_count - len(all_fcs)
        if excluded_count > 0:
            print(f"Excluded {excluded_count} feature classes containing '{exclude}'")
    
    # Filter to only feature classes with pagename fields (nested admin boundaries)
    eligible_fcs = []
    for fc in all_fcs:
        try:
            # Check if it has a pagename field using get_active_field
            fc_path = os.path.join(input_gdb, fc)
            get_active_field(fc_path)  # Will raise ValueError if no pagename field found
            eligible_fcs.append(fc)
        except ValueError:
            # Skip feature classes without pagename fields
            pass
    
    if not eligible_fcs:
        print(f"No eligible polygon feature classes found with pagename fields")
        return (0, 0, 0)
    
    print(f"Found {len(eligible_fcs)} eligible polygon feature classes to process")
    
    successful_count = 0
    failed_count = 0
    
    for i, fc in enumerate(eligible_fcs, 1):
        fc_path = os.path.join(input_gdb, fc)
        print(f"\n{'='*60}")
        print(f"Processing {i}/{len(eligible_fcs)}: {fc}")
        print(f"{'='*60}")
        
        try:
            calculate_page_orientation(fc_path)
            successful_count += 1
            print(f"✓ Successfully processed: {fc}")
        except Exception as e:
            failed_count += 1
            print(f"✗ Failed to process {fc}: {str(e)}")
    
    return (successful_count, failed_count, len(eligible_fcs))

# Main execution
if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) > 1:
        input_path = sys.argv[1]
        pattern = sys.argv[2] if len(sys.argv) > 2 else "*"
        exclude = sys.argv[3] if len(sys.argv) > 3 else None
    else:
        # Default hardcoded paths for testing
        # Option 1: Process a single feature class
        # input_path = r"E:\mheaton\cartography\COD_EAF_reference_microplanning_consolidation_20241121\data\20241205\processed\processed.gdb\GRID3_COD_health_areas_v4_0_pagename_airesante_dissolved"
        
        # Option 2: Process entire geodatabase
        input_path = r"D:\mheaton\Cartography\RDC_EAF\data\20251208\scratch\boundaryJoins_20251209.gdb"
        
        # Pattern to match nested admin boundary feature classes
        pattern = "*_nested_*"
        
        # Optional: exclude temporary or backup feature classes
        exclude = None  # or "temp", "_backup", etc.
    
    try:
        # Verify input exists
        if not arcpy.Exists(input_path):
            raise ValueError(f"Input does not exist: {input_path}")
        
        # Check if input is a geodatabase or a feature class
        desc = arcpy.Describe(input_path)
        
        if desc.dataType == "Workspace":
            # Process entire geodatabase
            print("Input is a geodatabase - processing all eligible feature classes")
            successful, failed, total = process_geodatabase(input_path, pattern, exclude)
            
            print(f"\n{'='*60}")
            print(f"BATCH PROCESSING COMPLETE")
            print(f"{'='*60}")
            print(f"  Total feature classes: {total}")
            print(f"  Successful: {successful}")
            print(f"  Failed: {failed}")
            print(f"{'='*60}")
            
            if failed > 0:
                sys.exit(1)
                
        elif desc.dataType == "FeatureClass":
            # Process single feature class
            print("Input is a feature class - processing single file")
            calculate_page_orientation(input_path)
            print("\nScript completed successfully!")
            
        else:
            raise ValueError(f"Unsupported input type: {desc.dataType}. Expected Workspace or FeatureClass.")
        
    except Exception as e:
        print(f"\nScript failed with error: {str(e)}")
        sys.exit(1)
