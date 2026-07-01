import arcpy
from arcpy import env
import os
import json
from datetime import datetime

def convert_polygons_to_lines(input_gdb, pattern="*", suffix="_lineFC", simplify=True, tolerance="2 Meters", create_summary=True):
    """
    Convert polygon feature classes to line feature classes in the same geodatabase.
    
    Parameters:
    input_gdb (str): Path to the input geodatabase
    pattern (str): Pattern to match feature classes (default: "*" for all)
    suffix (str): Suffix to add to output line feature class names
    simplify (bool): Whether to simplify the output lines (default: True)
    tolerance (str): Simplification tolerance with units (default: "2 Meters")
                    Recommended for 1:10,000 scale maps
    create_summary (bool): Whether to create a JSON summary file with vertex counts (default: True)
    
    Returns:
    list: List of line feature class names created
    """
    # Set environment settings
    env.workspace = input_gdb
    env.overwriteOutput = True
    
    print(f"Processing geodatabase: {input_gdb}")
    if simplify:
        print(f"Simplification enabled with tolerance: {tolerance}")
        
    # Find all feature classes matching the pattern
    all_fcs = arcpy.ListFeatureClasses(pattern)
    
    if not all_fcs:
        print(f"No feature classes found matching pattern: {pattern}")
        return []
    
    print(f"Found {len(all_fcs)} feature classes to examine")
    
    line_outputs = []
    polygon_count = 0
    summary_data = {
        "processing_info": {
            "timestamp": datetime.now().isoformat(),
            "input_geodatabase": input_gdb,
            "pattern": pattern,
            "simplification_enabled": simplify,
            "tolerance": tolerance if simplify else "N/A"
        },
        "feature_classes": []
    }

    def count_vertices(feature_class):
        """Count total vertices in a polygon feature class"""
        total_vertices = 0
        with arcpy.da.SearchCursor(feature_class, ["SHAPE@"]) as cursor:
            for row in cursor:
                if row[0]:  # Check if geometry exists
                    total_vertices += row[0].pointCount
        return total_vertices
    
    for fc in all_fcs:
        print(f"Examining: {fc}")
        
        try:            
            # Check if it's a polygon feature class
            desc = arcpy.Describe(fc)
            if desc.shapeType != "Polygon":
                print(f"  Skipping - not a polygon (Type: {desc.shapeType})")
                continue
            
            polygon_count += 1
            
            # Count vertices in original polygon (if create_summary is enabled)
            original_vertices = 0
            simplified_vertices = 0
            if create_summary:
                print(f"  Counting vertices in original polygon...")
                original_vertices = count_vertices(fc)
                print(f"  Original vertices: {original_vertices:,}")
            
            # Generate output line feature class name
            base_name = fc
            if base_name.endswith("_pagename"):
                # Remove _pagename suffix before adding line suffix
                base_name = base_name[:-len("_pagename")]
            
            line_output = f"{base_name}{suffix}"
            print(f"  Preparing to convert polygon to line: {fc} -> {line_output}")# Initialize variables
            temp_simplified = None
            simplified_poly_output = None
            
            # Simplify polygons using Simplify Shared Edges if requested
            if simplify:
                # Create tolerance suffix (remove spaces and convert to lowercase)
                tolerance_suffix = tolerance.replace(" ", "").lower()
                simplified_poly_output = f"{base_name}_simplified{tolerance_suffix}"
                line_output = f"{base_name}_simplified{tolerance_suffix}{suffix}"
                
                scratch_gdb = r"E:\\mheaton\\cartography\\GRID_2025\\RDC_EAF_summer_2025\\data\\20250625\\scratch\\temp.gdb"
                temp_simplified = f"{scratch_gdb}/{base_name}_temp_simplified"
                print(f"  Creating temporary copy of {fc} in scratch geodatabase")
                try:
                    arcpy.management.CopyFeatures(fc, temp_simplified)
                    print(f"  Simplifying polygons with shared edges, tolerance: {tolerance}")
                    arcpy.cartography.SimplifySharedEdges(
                        in_features=temp_simplified,
                        tolerance=tolerance
                    )                    
                    # Copy simplified polygons to output geodatabase
                    print(f"  Saving simplified polygons as: {simplified_poly_output}")
                    arcpy.management.CopyFeatures(temp_simplified, simplified_poly_output)
                    
                    # Count vertices in simplified polygon (if create_summary is enabled)
                    if create_summary:
                        print(f"  Counting vertices in simplified polygon...")
                        simplified_vertices = count_vertices(temp_simplified)
                        print(f"  Simplified vertices: {simplified_vertices:,}")
                    
                    poly_to_line_input = temp_simplified
                except Exception as simplify_error:
                    print(f"  Warning: SimplifySharedEdges failed for {fc}: {str(simplify_error)}")
                    print(f"  Proceeding with original polygons for line conversion.")
                    poly_to_line_input = fc
                    temp_simplified = None  # Reset since we're not using temp copy
            else:
                poly_to_line_input = fc

            # Convert (possibly simplified) polygons to lines
            print(f"  Converting polygons to lines: {line_output}")
            arcpy.management.PolygonToLine(poly_to_line_input, line_output)            # Clean up temporary files in scratch geodatabase (only if temp was created)
            if temp_simplified and arcpy.Exists(temp_simplified):
                try:
                    print(f"  Cleaning up temporary dataset: {temp_simplified}")
                    arcpy.management.Delete(temp_simplified)
                except Exception as cleanup_error:
                    print(f"  Warning: Failed to delete temporary dataset {temp_simplified}: {str(cleanup_error)}")
            
            # Report success for both simplified polygons and line outputs
            success_count = 0
            if simplified_poly_output and arcpy.Exists(simplified_poly_output):
                print(f"  Successfully created simplified polygons: {simplified_poly_output}")
                success_count += 1
            
            if arcpy.Exists(line_output):
                print(f"  Successfully created line feature class: {line_output}")
                line_outputs.append(line_output)
                success_count += 1
            
            if success_count == 0:
                print(f"  Failed to create outputs for: {fc}")
            
            # Add to summary data if enabled
            if create_summary:
                fc_summary = {
                    "feature_class": fc,
                    "base_name": base_name,
                    "processing_date": datetime.now().isoformat(),
                    "original_vertices": original_vertices,
                    "simplified_vertices": simplified_vertices if simplify else "N/A",
                    "vertex_reduction": {
                        "absolute": original_vertices - simplified_vertices if simplify and simplified_vertices > 0 else "N/A",
                        "percentage": round(((original_vertices - simplified_vertices) / original_vertices * 100), 2) if simplify and simplified_vertices > 0 else "N/A"
                    },
                    "outputs_created": {
                        "simplified_polygons": simplified_poly_output if simplified_poly_output and arcpy.Exists(simplified_poly_output) else None,
                        "line_features": line_output if arcpy.Exists(line_output) else None
                    }
                }
                summary_data["feature_classes"].append(fc_summary)
                
        except Exception as e:
            print(f"  Error processing {fc}: {str(e)}")
            if create_summary:
                fc_summary = {
                    "feature_class": fc,
                    "base_name": base_name if 'base_name' in locals() else "N/A",
                    "processing_date": datetime.now().isoformat(),
                    "error": str(e),
                    "original_vertices": "Error",
                    "simplified_vertices": "Error",
                    "vertex_reduction": "Error",                    
                    "outputs_created": None
                }
                summary_data["feature_classes"].append(fc_summary)
    
    print(f"\nConversion complete:")
    print(f"  Examined {len(all_fcs)} feature classes")
    print(f"  Found {polygon_count} polygon feature classes")
    print(f"  Successfully created {len(line_outputs)} line feature classes")
    
    # Create JSON summary file if enabled
    if create_summary and summary_data["feature_classes"]:
        try:
            gdb_folder = os.path.dirname(input_gdb)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_filename = f"polygon_to_line_summary_{timestamp}.json"
            json_path = os.path.join(gdb_folder, json_filename)
            
            # Add summary statistics
            summary_data["summary_statistics"] = {
                "total_feature_classes_examined": len(all_fcs),
                "polygon_feature_classes_found": polygon_count,
                "line_feature_classes_created": len(line_outputs),
                "total_original_vertices": sum(fc.get("original_vertices", 0) for fc in summary_data["feature_classes"] if isinstance(fc.get("original_vertices"), int)),
                "total_simplified_vertices": sum(fc.get("simplified_vertices", 0) for fc in summary_data["feature_classes"] if isinstance(fc.get("simplified_vertices"), int)),
            }
            
            # Calculate overall vertex reduction
            total_orig = summary_data["summary_statistics"]["total_original_vertices"]
            total_simp = summary_data["summary_statistics"]["total_simplified_vertices"]
            if total_orig > 0 and total_simp > 0:
                overall_reduction = round(((total_orig - total_simp) / total_orig * 100), 2)
                summary_data["summary_statistics"]["overall_vertex_reduction_percentage"] = overall_reduction
            else:
                summary_data["summary_statistics"]["overall_vertex_reduction_percentage"] = "N/A"
            
            with open(json_path, 'w') as json_file:
                json.dump(summary_data, json_file, indent=2)
            
            print(f"\nSummary JSON created: {json_path}")
            
        except Exception as json_error:
            print(f"Warning: Failed to create JSON summary: {str(json_error)}")
    
    return line_outputs

def convert_polygons_to_lines_multi(input_gdb, pattern="*", tolerances=("8 Meters","30 Meters","70 Meters","200 Meters"),
                                    suffix="_lineFC", create_summary=True, algorithm="WEIGHTED_AREA", output_root=None):
    """
    Batch version: for each polygon FC, produce simplified + line outputs for each tolerance.
    CRITICAL FIX: Processes ALL hierarchical feature classes TOGETHER for each tolerance
    to maintain shared edge alignment between parent and child administrative units.

    Parameters:
        input_gdb (str): Input geodatabase path
        pattern (str): Feature class name pattern
        tolerances (iterable[str]): e.g. ("20 Meters","100 Meters","250 Meters","500 Meters")
        suffix (str): Suffix appended to line output layer names
        create_summary (bool): Write JSON with vertex statistics
        algorithm (str): Simplification algorithm (POINT_REMOVE | BEND_SIMPLIFY | WEIGHTED_AREA | EFFECTIVE_AREA)
        output_root (str): Root directory for output structure. If None, uses input_gdb directory.
                          Will create: output_root/generalization/{scale}/{polygon.gdb, line.gdb}
    """
    # Map tolerance to scale folder (matches move_to_scaleDirs.py)
    tolerance_to_scale = {
        "20 Meters": "50k",
        "20meters": "50k",
        "100 Meters": "200k",
        "100meters": "200k",
        "250 Meters": "400k",
        "250meters": "400k",
        "500 Meters": "800k",
        "500meters": "800k"
    }
    
    env.workspace = input_gdb
    env.overwriteOutput = True
    
    # Determine output root directory
    if output_root is None:
        output_root = os.path.dirname(input_gdb)
    
    # Check that generalization folder structure exists
    generalization_root = os.path.join(output_root, "generalization")
    print(f"Output root: {output_root}")
    print(f"Generalization structure: {generalization_root}")
    
    # Validate structure exists BEFORE processing
    print("\nValidating output structure...")
    if not os.path.exists(generalization_root):
        raise FileNotFoundError(
            f"ERROR: Generalization folder does not exist: {generalization_root}\n"
            f"Please run 0_mkDir.py first to create the required directory structure."
        )
    
    # Check that all required scale folders and geodatabases exist
    required_scales = set(tolerance_to_scale.values())  # Get unique scale folders needed
    missing_items = []
    
    for scale in required_scales:
        scale_path = os.path.join(generalization_root, scale)
        if not os.path.exists(scale_path):
            missing_items.append(f"  - Scale folder: {scale_path}")
        else:
            # Check for polygon.gdb and line.gdb
            for gdb_name in ["polygon.gdb", "line.gdb"]:
                gdb_path = os.path.join(scale_path, gdb_name)
                if not arcpy.Exists(gdb_path):
                    missing_items.append(f"  - Geodatabase: {gdb_path}")
    
    if missing_items:
        error_msg = (
            f"ERROR: Required output structure is incomplete. Missing items:\n" +
            "\n".join(missing_items) +
            f"\n\nPlease run 0_mkDir.py first to create the required directory structure."
        )
        raise FileNotFoundError(error_msg)
    
    print(f"✓ Output structure validated - all required folders and geodatabases exist")
    print(f"  Required scales: {', '.join(sorted(required_scales))}\n")
    
    all_fcs = arcpy.ListFeatureClasses(pattern)
    if not all_fcs:
        print("No feature classes found.")
        return {}

    # Filter to polygon feature classes only
    polygon_fcs = []
    for fc in all_fcs:
        try:
            d = arcpy.Describe(fc)
            if d.shapeType == "Polygon":
                polygon_fcs.append(fc)
        except:
            continue
    
    if not polygon_fcs:
        print("No polygon feature classes found.")
        return {}

    # Ensure scratch GDB exists (fallback to env.scratchGDB otherwise)
    scratch_gdb = env.scratchGDB
    results = {}
    summary = []
    print(f"Processing {len(polygon_fcs)} polygon FCs across {len(tolerances)} tolerances (algorithm={algorithm})")
    print(f"HIERARCHICAL MODE: All FCs will be simplified TOGETHER to maintain shared edge alignment\n")

    def count_vertices(fc):
        total = 0
        with arcpy.da.SearchCursor(fc, ["SHAPE@"]) as cur:
            for r in cur:
                if r[0]:
                    total += r[0].pointCount
        return total

    # Count original vertices for all FCs (once, before any simplification)
    original_vertex_counts = {}
    if create_summary:
        print("Counting original vertices for all feature classes...")
        for fc in polygon_fcs:
            try:
                original_vertex_counts[fc] = count_vertices(fc)
                print(f"  {fc}: {original_vertex_counts[fc]:,} vertices")
            except Exception as e:
                print(f"  Error counting vertices for {fc}: {e}")
                original_vertex_counts[fc] = None

    # Process each tolerance level - ALL FCs together to maintain shared edges
    for tol in tolerances:
        tol_tag = tol.replace(" ", "").lower()  # e.g. 20meters
        
        # Determine output scale folder
        scale = tolerance_to_scale.get(tol) or tolerance_to_scale.get(tol_tag)
        if not scale:
            print(f"WARNING: No scale mapping for tolerance '{tol}' - skipping")
            continue
        
        # Define output geodatabase paths
        polygon_gdb = os.path.join(generalization_root, scale, "polygon.gdb")
        line_gdb = os.path.join(generalization_root, scale, "line.gdb")
        
        print(f"\n{'='*80}")
        print(f"PROCESSING TOLERANCE: {tol} (tag: {tol_tag}) → SCALE: {scale}")
        print(f"{'='*80}")
        print(f"  Polygon output: {polygon_gdb}")
        print(f"  Line output: {line_gdb}")
        
        # Step 1: Copy all FCs to polygon.gdb with simplified names
        simplified_fcs = []
        for fc in polygon_fcs:
            base_name = fc[:-len("_pagename")] if fc.endswith("_pagename") else fc
            simplified_fc_name = f"{base_name}_simp_{tol_tag}"
            simplified_fc = os.path.join(polygon_gdb, simplified_fc_name)
            
            try:
                if not arcpy.Exists(simplified_fc):
                    print(f"  Copying {fc} -> {simplified_fc_name}")
                    arcpy.management.CopyFeatures(fc, simplified_fc)
                    simplified_fcs.append(simplified_fc)
                else:
                    print(f"  Using existing: {simplified_fc_name}")
                    simplified_fcs.append(simplified_fc)
            except Exception as copy_err:
                print(f"  ERROR copying {fc}: {copy_err}")
                continue
        
        # Step 2: Simplify ALL hierarchical FCs TOGETHER (this maintains shared edges!)
        if simplified_fcs:
            try:
                print(f"\n  SIMPLIFYING {len(simplified_fcs)} FCs TOGETHER with shared edges @ {tol}...")
                print(f"  Algorithm: {algorithm}")
                print(f"  Feature classes: {', '.join([os.path.basename(fc) for fc in simplified_fcs])}")
                
                # SimplifySharedEdges can accept multiple feature classes to maintain alignment
                arcpy.cartography.SimplifySharedEdges(simplified_fcs, algorithm, tol)
                print(f"  ✓ Simplification complete - shared edges maintained across all hierarchies")
                
            except Exception as simp_err:
                print(f"  WARNING: SimplifySharedEdges failed for tolerance {tol}: {simp_err}")
                print(f"  Proceeding with unsimplified geometries")
        
        # Step 3: Convert each simplified polygon to lines
        print(f"\n  CONVERTING POLYGONS TO LINES...")
        for fc in polygon_fcs:
            base_name = fc[:-len("_pagename")] if fc.endswith("_pagename") else fc
            simplified_fc_name = f"{base_name}_simp_{tol_tag}"
            simplified_fc = os.path.join(polygon_gdb, simplified_fc_name)
            line_fc_name = f"{simplified_fc_name}{suffix}"
            line_fc = os.path.join(line_gdb, line_fc_name)
            
            if fc not in results:
                results[fc] = []
            
            # Skip if line FC already exists
            if arcpy.Exists(line_fc):
                print(f"  Skip (exists): {line_fc_name}")
                results[fc].append({"tolerance": tol, "scale": scale, "simplified_fc": simplified_fc, "line_fc": line_fc, "skipped": True})
                continue
            
            # Convert polygon to line (1:1 geometry, no further simplification)
            try:
                print(f"  PolygonToLine: {simplified_fc_name} -> {line_fc_name}")
                arcpy.management.PolygonToLine(simplified_fc, line_fc)
                print(f"  ✓ Line FC created (geometry matches simplified polygon exactly)")
                
            except Exception as line_err:
                print(f"  ERROR: PolygonToLine failed for {simplified_fc_name}: {line_err}")
                continue
            
            # Count simplified vertices for summary
            simp_vertices = None
            if create_summary and arcpy.Exists(simplified_fc):
                try:
                    simp_vertices = count_vertices(simplified_fc)
                except Exception as count_err:
                    print(f"  Warning: Could not count vertices for {simplified_fc}: {count_err}")
            
            results[fc].append({
                "tolerance": tol,
                "scale": scale,
                "simplified_fc": simplified_fc,
                "line_fc": line_fc,
                "algorithm": algorithm
            })
            
            # Add to summary
            if create_summary:
                original_vertices = original_vertex_counts.get(fc)
                if original_vertices and simp_vertices:
                    vr_abs = original_vertices - simp_vertices
                    vr_pct = round(vr_abs / original_vertices * 100, 2) if original_vertices else None
                else:
                    vr_abs = None
                    vr_pct = None
                
                summary.append({
                    "feature_class": fc,
                    "tolerance": tol,
                    "scale": scale,
                    "algorithm": algorithm,
                    "original_vertices": original_vertices,
                    "simplified_vertices": simp_vertices,
                    "vertex_reduction_abs": vr_abs,
                    "vertex_reduction_pct": vr_pct,
                    "line_fc": line_fc,
                    "simplified_fc": simplified_fc,
                    "polygon_gdb": polygon_gdb,
                    "line_gdb": line_gdb
                })

    if create_summary and summary:
        try:
            out_json = os.path.join(os.path.dirname(input_gdb),
                                    f"polygon_to_line_multi_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            with open(out_json, "w") as f:
                json.dump({"summary": summary}, f, indent=2)
            print(f"\nSummary written: {out_json}")
        except Exception as json_err:
            print(f"Failed writing summary JSON: {json_err}")
    return results

if __name__ == "__main__":
    # Four-scale strategy: 20m→50k, 100m→200k, 250m→400k, 500m→800k
    # Outputs saved to: output_root/generalization/{scale}/{polygon.gdb, line.gdb}
    
    input_gdb = r"D:\mheaton\Cartography\RDC_EAF\data\20251208\scratch\boundaryJoins_20251209.gdb"
    output_root = r"D:\mheaton\Cartography\RDC_EAF\data\20251209\processed"
    pattern = "*_nested_*"
    tolerance_set = ("20 Meters", "100 Meters", "250 Meters", "500 Meters")
    
    print(f"=" * 80)
    print(f"ADMINISTRATIVE BOUNDARY SIMPLIFICATION")
    print(f"=" * 80)
    print(f"Input GDB: {input_gdb}")
    print(f"Output Root: {output_root}")
    print(f"Pattern: {pattern}")
    print(f"Tolerances: {', '.join(tolerance_set)}")
    print(f"=" * 80)
    
    convert_polygons_to_lines_multi(
        input_gdb=input_gdb,
        pattern=pattern,
        tolerances=tolerance_set,
        create_summary=True,
        algorithm="WEIGHTED_AREA",
        output_root=output_root
    )
