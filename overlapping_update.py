def find_overlapping_enodebs(target_enb, latitude, longitude):
    target_enb = str(target_enb)
    probe = make_probe(target_enb, grab_url, enb_of_cell)
    result = adaptive_coverage_scan(target_enb, latitude, longitude, probe)

    neighbour_enbs = set()
    for point in result["points"]:
        # all cells present at this point (serving + top1..topN)
        enbs_here = set()
        for record in point.get("raw", {}).get("array", []):
            for cell in record.get("info", {}).values():
                if isinstance(cell, dict) and cell.get("sector_name"):
                    enbs_here.add(enb_of_cell(cell["sector_name"]))

        if target_enb not in enbs_here:
            continue  # target isn't even present here -> not its coverage

        for nb in enbs_here:
            if nb and nb != target_enb:
                neighbour_enbs.add(nb)

    neighbour_enbs = sorted(neighbour_enbs)
    print(f"Target eNodeB {target_enb}: "
          f"{len(neighbour_enbs)} overlapping neighbour eNodeB(s) found")
    return neighbour_enbs
