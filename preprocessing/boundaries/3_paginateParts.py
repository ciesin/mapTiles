import arcpy
import os

# todo: dissolve and re-explode multipart features
# truncate minus one to get unpaginated names
# then dissolve on these

def add_pagination_fields(gdb_path, admin_fields, pattern="*"):
    """
    For each feature class in the input geodatabase, add pagination fields (pageNum, pageTotal).
    Optionally filter feature classes by a pattern (e.g., "*_nested_*").
    Args:
        gdb_path (str): Path to the geodatabase containing dissolved feature classes.
        admin_fields (list): List of administrative field names (in order of dissolve).
        pattern (str): Pattern to match feature classes (default: "*" for all)
    """
    arcpy.env.workspace = gdb_path
    fcs = arcpy.ListFeatureClasses(pattern)
    print(f"Found {len(fcs)} feature classes in {gdb_path} matching pattern '{pattern}'")
    for i, admin in enumerate(admin_fields):
        pagename_field = f"pagename_{admin}"
        # Find the feature class for this admin level
        matching_fcs = [fc for fc in fcs if pagename_field in [f.name for f in arcpy.ListFields(fc)]]
        for fc in matching_fcs:
            print(f"Processing {fc} for admin level '{admin}'...")
            # Add pageNum and pageTotal fields if not present
            existing_fields = [f.name for f in arcpy.ListFields(fc)]
            for fld in ("pageNum", "pageTotal"):
                if fld not in existing_fields:
                    arcpy.AddField_management(fc, fld, "LONG")
            # Build mapping: pagename -> list of (oid, area)
            grouped = {}
            with arcpy.da.SearchCursor(fc, ["OID@", "SHAPE@AREA", pagename_field]) as scur:
                for oid, area, pname in scur:
                    if pname:
                        grouped.setdefault(pname, []).append((oid, area))
            # Assign pageNum and pageTotal
            mapping = {}
            for pname, recs in grouped.items():
                recs_sorted = sorted(recs, key=lambda x: x[1], reverse=True)
                total = len(recs_sorted)
                for idx, (oid, _) in enumerate(recs_sorted, start=1):
                    mapping[oid] = (idx, total)
            # Update fields
            with arcpy.da.UpdateCursor(fc, ["OID@", "pageNum", "pageTotal", pagename_field]) as ucur:
                for row in ucur:
                    oid = row[0]
                    num, total = mapping.get(oid, (1, 1))
                    row[1] = num
                    row[2] = total
                    # Do NOT modify pagename field - only keep in pageNum 
                    ucur.updateRow(row)
            print(f"  Updated {len(grouped)} unique pagenames for {fc}")
    print("Pagination logic complete for all feature classes.")

if __name__ == "__main__":
    # Example usage
    gdb_path = r"D:\mheaton\Cartography\RDC_EAF\data\20251208\scratch\boundaryJoins_20251209.gdb"
    admin_fields = ["province", "antenne", "zonesante", "airesante"]
    # Optional: specify a pattern to match only certain feature classes
    pattern = "*_nested_*"  # Adjust as needed
    add_pagination_fields(gdb_path, admin_fields, pattern)
