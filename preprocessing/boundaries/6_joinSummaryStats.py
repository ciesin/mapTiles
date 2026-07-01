import arcpy
import os

def remove_duplicate_fields(fc_path):
    """
    Remove duplicate fields that have identical contents.
    For example, if 'zonesante' and 'zonesante_1' have identical values, remove 'zonesante_1'.
    
    Args:
        fc_path (str): Path to the feature class
        
    Returns:
        int: Number of duplicate fields removed
    """
    print("  Checking for duplicate fields with identical contents...")
    
    # Get all fields (exclude system fields)
    all_fields = arcpy.ListFields(fc_path)
    data_fields = [f for f in all_fields if f.type not in ('OID', 'Geometry') and f.name.upper() not in ('OBJECTID', 'SHAPE', 'FID')]
    
    # Group fields by base name (without suffix like '_1', '_2', etc.)
    field_groups = {}
    for field in data_fields:
        # Extract base name by removing common duplicate suffixes
        base_name = field.name
        if '_1' in field.name and field.name.endswith('_1'):
            base_name = field.name[:-2]
        elif '_2' in field.name and field.name.endswith('_2'):
            base_name = field.name[:-2]
        elif '_12' in field.name and field.name.endswith('_12'):
            base_name = field.name[:-3]
        
        if base_name not in field_groups:
            field_groups[base_name] = []
        field_groups[base_name].append(field.name)
    
    # Find groups with potential duplicates
    duplicate_candidates = {base: fields for base, fields in field_groups.items() if len(fields) > 1}
    
    if not duplicate_candidates:
        print("    No potential duplicate fields found")
        return 0
    
    print(f"    Found {len(duplicate_candidates)} field groups with potential duplicates")
    
    fields_to_remove = []
    
    # Check each group for identical content
    for base_name, field_list in duplicate_candidates.items():
        print(f"    Checking field group: {base_name} -> {field_list}")
        
        # Sort to prioritize original field name (without suffix)
        field_list.sort(key=lambda x: (len(x), x))
        primary_field = field_list[0]  # Use shortest/first as primary
        
        # Get sample of values to compare (using first 100 rows for efficiency)
        try:
            with arcpy.da.SearchCursor(fc_path, field_list, sql_clause=(None, "ORDER BY OBJECTID")) as cursor:
                rows_checked = 0
                identical_fields = set(field_list[1:])  # Start with all potential duplicates
                
                for row in cursor:
                    if rows_checked >= 100:  # Limit sample size for performance
                        break
                    
                    primary_value = row[0]  # Value from primary field
                    
                    # Check each potential duplicate
                    for i, field_name in enumerate(field_list[1:], 1):
                        if field_name in identical_fields:
                            duplicate_value = row[i]
                            if primary_value != duplicate_value:
                                # Values differ, not a true duplicate
                                identical_fields.discard(field_name)
                                print(f"      {field_name} differs from {primary_field} (row {rows_checked + 1})")
                    
                    rows_checked += 1
                    
                    # If no identical fields remain, break early
                    if not identical_fields:
                        break
                
                # Add confirmed duplicates to removal list
                if identical_fields:
                    fields_to_remove.extend(identical_fields)
                    print(f"      Will remove identical duplicates: {list(identical_fields)}")
                
        except Exception as e:
            print(f"      Error checking field group {base_name}: {e}")
            continue
    
    # Remove duplicate fields
    removed_count = 0
    if fields_to_remove:
        try:
            print(f"    Removing {len(fields_to_remove)} duplicate fields...")
            arcpy.DeleteField_management(fc_path, fields_to_remove)
            removed_count = len(fields_to_remove)
            print(f"    Successfully removed: {fields_to_remove}")
        except Exception as e:
            print(f"    Error removing fields: {e}")
    else:
        print("    No duplicate fields to remove")
    
    return removed_count

def join_summary_stats_to_polygons(gdb_path, summary_stats_gdb, admin_hierarchy):
    """
    Join summary statistics tables to their corresponding polygon feature classes.
    
    Args:
        gdb_path (str): Path to the geodatabase containing polygon feature classes with pagename fields.
        summary_stats_gdb (str): Path to the geodatabase containing summary statistics tables.
        admin_hierarchy (list): List of admin levels from coarsest to finest (e.g., ["province", "antenne", "zonesante", "airesante"])
    """
    arcpy.env.workspace = gdb_path
    arcpy.env.overwriteOutput = True
    
    print("Starting summary statistics join process...")
    print(f"Polygon geodatabase: {gdb_path}")
    print(f"Summary statistics geodatabase: {summary_stats_gdb}")
    print(f"Administrative hierarchy: {admin_hierarchy}")
    
    # Get all feature classes in the polygon geodatabase
    all_fcs = arcpy.ListFeatureClasses()
    
    # Map admin level to feature class
    polygon_fcs = {}
    for admin in admin_hierarchy:
        pagename_field = f"pagename_{admin}"
        for fc in all_fcs:
            if pagename_field in [f.name for f in arcpy.ListFields(fc)]:
                polygon_fcs[admin] = fc
                break
    
    print(f"Found polygon feature classes: {polygon_fcs}")
    
    # Process each admin level
    success_count = 0
    for admin in admin_hierarchy:
        polygon_fc = polygon_fcs.get(admin)
        if not polygon_fc:
            print(f"Skipping {admin}: no polygon feature class found.")
            continue
            
        print(f"\nProcessing admin level: {admin}")
        print(f"  Polygon FC: {polygon_fc}")
        
        # Find corresponding summary table
        summary_table_pattern = f"*summary_{admin}"
        arcpy.env.workspace = summary_stats_gdb
        summary_tables = arcpy.ListTables(summary_table_pattern)
        
        if not summary_tables:
            print(f"  Warning: No summary table found for {admin} in {summary_stats_gdb}")
            continue
            
        summary_table = summary_tables[0]  # Take the first match
        summary_table_path = os.path.join(summary_stats_gdb, summary_table)
        print(f"  Summary table: {summary_table}")
        
        # Verify the pagename field exists in both
        pagename_field = f"pagename_{admin}"
        polygon_fc_path = os.path.join(gdb_path, polygon_fc)
        
        polygon_fields = [f.name for f in arcpy.ListFields(polygon_fc_path)]
        summary_fields = [f.name for f in arcpy.ListFields(summary_table_path)]
        
        if pagename_field not in polygon_fields:
            print(f"  Error: {pagename_field} not found in polygon FC {polygon_fc}")
            continue
            
        if pagename_field not in summary_fields:
            print(f"  Error: {pagename_field} not found in summary table {summary_table}")
            continue
        
        # Create output feature class name
        output_fc_name = f"{polygon_fc}_withStats"
        output_fc_path = os.path.join(gdb_path, output_fc_name)
        
        # Delete output if it exists
        if arcpy.Exists(output_fc_path):
            arcpy.Delete_management(output_fc_path)
            print(f"  Deleted existing output: {output_fc_name}")
        
        try:
            # Capture original field aliases from polygon FC
            print("  Capturing original field aliases...")
            original_aliases = {}
            for field in arcpy.ListFields(polygon_fc_path):
                if field.aliasName and field.aliasName != field.name:
                    original_aliases[field.name] = field.aliasName
            
            # Capture field aliases from summary table
            summary_aliases = {}
            for field in arcpy.ListFields(summary_table_path):
                if field.aliasName and field.aliasName != field.name:
                    summary_aliases[field.name] = field.aliasName
            
            # Perform the join using JoinField
            print(f"  Joining summary table to polygon FC on {pagename_field}...")
            
            # First, copy the polygon FC to preserve original
            arcpy.management.CopyFeatures(polygon_fc_path, output_fc_path)
            
            # Get fields to join (exclude system fields and the join field itself)
            fields_to_join = []
            exclude_fields = ['OBJECTID', 'Shape', 'SHAPE', 'FID', pagename_field]
            
            for field in arcpy.ListFields(summary_table_path):
                if (field.name not in exclude_fields and 
                    field.type not in ('OID', 'Geometry')):
                    fields_to_join.append(field.name)
            
            print(f"  Joining {len(fields_to_join)} fields from summary table...")
              # Perform the join
            arcpy.management.JoinField(
                in_data=output_fc_path,
                in_field=pagename_field,
                join_table=summary_table_path,
                join_field=pagename_field,
                fields=fields_to_join
            )
            
            # Remove duplicate fields with identical contents
            removed_duplicates = remove_duplicate_fields(output_fc_path)
            if removed_duplicates > 0:
                print(f"  Removed {removed_duplicates} duplicate fields")
            
            # Restore field aliases
            print("  Restoring field aliases...")
            restored_count = 0
              # Restore original polygon field aliases
            for field_name, alias in original_aliases.items():
                try:
                    arcpy.management.AlterField(output_fc_path, field_name, new_field_alias=alias)
                    restored_count += 1
                except Exception as e:
                    print(f"    Warning: Could not restore alias for {field_name}: {e}")
            
            # Apply summary table field aliases to joined fields
            for field_name, alias in summary_aliases.items():
                try:
                    # Check if field exists in output (some fields might not have been joined)
                    output_fields = [f.name for f in arcpy.ListFields(output_fc_path)]
                    if field_name in output_fields:
                        arcpy.management.AlterField(output_fc_path, field_name, new_field_alias=alias)
                        restored_count += 1
                except Exception as e:
                    print(f"    Warning: Could not set alias for {field_name}: {e}")
            
            print(f"  Successfully joined summary statistics to {output_fc_name}")
            print(f"  Restored {restored_count} field aliases")
            
            # Verify the join worked
            result_count = int(arcpy.GetCount_management(output_fc_path).getOutput(0))
            original_count = int(arcpy.GetCount_management(polygon_fc_path).getOutput(0))
            print(f"  Output feature count: {result_count} (original: {original_count})")
            
            success_count += 1
            
        except Exception as e:
            print(f"  Error processing {admin}: {e}")
            # Clean up failed output
            if arcpy.Exists(output_fc_path):
                try:
                    arcpy.Delete_management(output_fc_path)
                except:
                    pass
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY STATISTICS JOIN COMPLETE")
    print("="*60)
    print(f"Successfully processed {success_count} of {len(admin_hierarchy)} administrative levels")
    print(f"Output location: {gdb_path}")
    
    if success_count > 0:
        print("\nOutput feature classes created:")
        arcpy.env.workspace = gdb_path
        stats_fcs = arcpy.ListFeatureClasses("*_withStats")
        for fc in stats_fcs:
            print(f"  - {fc}")
        
        print("\nFeatures of joined layers:")
        print("- Preserved original polygon geometry and all pagename fields")
        print("- Added summary statistics fields from corresponding tables")
        print("- Maintained original field aliases from both sources")
        print("- Ready for map series production")
    
    return success_count > 0

def validate_inputs(gdb_path, summary_stats_gdb, admin_hierarchy):
    """
    Validate input parameters before processing.
    
    Args:
        gdb_path (str): Path to polygon geodatabase
        summary_stats_gdb (str): Path to summary statistics geodatabase  
        admin_hierarchy (list): List of admin levels
        
    Returns:
        bool: True if all inputs are valid
    """
    print("Validating inputs...")
    
    # Check polygon geodatabase
    if not arcpy.Exists(gdb_path):
        print(f"ERROR: Polygon geodatabase not found: {gdb_path}")
        return False
    
    # Check summary stats geodatabase
    if not arcpy.Exists(summary_stats_gdb):
        print(f"ERROR: Summary statistics geodatabase not found: {summary_stats_gdb}")
        return False
    
    # Check admin hierarchy
    if not admin_hierarchy or not isinstance(admin_hierarchy, list):
        print(f"ERROR: Invalid admin_hierarchy. Must be a non-empty list.")
        return False
    
    print("✓ All inputs validated successfully")
    return True

if __name__ == "__main__":
    # Configuration
    gdb_path = r"E:\mheaton\cartography\GRID_2025\RDC_EAF_2025\data\20250521\scratch\boundaries.gdb"
    summary_stats_gdb = r"E:\mheaton\cartography\GRID_2025\RDC_EAF_2025\data\0_CONSOLIDATED\zdc_summaryStats_20250528.gdb"
    admin_hierarchy = ["province", "antenne", "zonesante", "airesante"]
    
    # Validate inputs
    if validate_inputs(gdb_path, summary_stats_gdb, admin_hierarchy):
        # Run the join process
        success = join_summary_stats_to_polygons(gdb_path, summary_stats_gdb, admin_hierarchy)
        
        if success:
            print("\npop_totalSummary statistics join completed successfully!")
        else:
            print("\npop_totalSummary statistics join completed with errors.")
    else:
        print("\npop_totalInput validation failed. Please check the configuration and try again.")