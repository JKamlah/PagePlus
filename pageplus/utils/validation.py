from typing import Any, Dict, List

from pageplus.utils.constants import PcGtsVersion


def validate_version_compatibility(root, target_version: PcGtsVersion) -> Dict[str, Any]:
    """
    Validates compatibility issues when converting to a target PAGE XML version.
    Returns a dictionary with warnings and errors about potential compatibility issues.
    
    Args:
        target_version (PcGtsVersion): The target PAGE XML version.
        
    Returns:
        Dict[str, Any]: Dictionary containing 'warnings', 'errors', and 'compatibility_score'
    """
    warnings = []
    errors = []
    compatibility_score = 100  # Start with perfect compatibility
    
    # Get current version from the root element
    current_ns = root.xpath('namespace-uri(.)').rsplit('/', 1)[1]
    current_version = None
    for version in PcGtsVersion:
        if version.value in current_ns:
            current_version = version
            break
    
    if current_version is None:
        warnings.append("Could not determine current PAGE XML version")
        return {"warnings": warnings, "errors": errors, "compatibility_score": 0}
    
    # If same version, no issues
    if current_version == target_version:
        return {"warnings": [], "errors": [], "compatibility_score": 100}
    
    # Check for major breaking changes
    if _is_downgrade(current_version, target_version):
        compatibility_score -= 20
        warnings.append(f"Downgrading from {current_version.value} to {target_version.value} may cause data loss")
    
    # Version-specific compatibility checks
    if target_version.value == "2013-07-15":
        compatibility_score = _check_2013_compatibility(root, warnings, errors, compatibility_score)
    elif target_version.value == "2015-07-15":
        compatibility_score = _check_2015_compatibility(root, warnings, errors, compatibility_score)
    elif target_version.value == "2016-07-15":
        compatibility_score = _check_2016_compatibility(root, warnings, errors, compatibility_score)
    elif target_version.value == "2017-07-15":
        compatibility_score = _check_2017_compatibility(root, warnings, errors, compatibility_score)
    elif target_version.value == "2018-07-15":
        compatibility_score = _check_2018_compatibility(root, warnings, errors, compatibility_score)
    elif target_version.value == "2019-07-15":
        compatibility_score = _check_2019_compatibility(root, warnings, errors, compatibility_score)
    
    return {
        "warnings": warnings,
        "errors": errors,
        "compatibility_score": max(0, compatibility_score),
        "current_version": current_version.value,
        "target_version": target_version.value
    }

def _is_downgrade(current: PcGtsVersion, target: PcGtsVersion) -> bool:
    """Check if converting from current to target is a downgrade."""
    version_order = [
        PcGtsVersion.V2010_01_12,
        PcGtsVersion.V2010_03_19,
        PcGtsVersion.V2013_07_15,
        PcGtsVersion.V2015_07_15,
        PcGtsVersion.V2016_07_15,
        PcGtsVersion.V2017_07_15,
        PcGtsVersion.V2018_07_15,
        PcGtsVersion.V2019_07_15
    ]
    current_idx = version_order.index(current) if current in version_order else -1
    target_idx = version_order.index(target) if target in version_order else -1
    return current_idx > target_idx

def _check_2013_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2013-07-15 version."""
    # Check for FrameRegion elements (removed in 2013)
    frame_regions = root.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}FrameRegion")
    if not frame_regions:
        frame_regions = root.findall(".//FrameRegion")
    
    if frame_regions:
        errors.append(f"Found {len(frame_regions)} FrameRegion elements. These were removed in 2013-07-15. Use GraphicRegion type='frame' instead.")
        score -= 30
    
    # Check for old Point-based Coords (changed to points attribute in 2013)
    point_coords = root.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}Point")
    if not point_coords:
        point_coords = root.findall(".//Point")
    
    if point_coords:
        warnings.append(f"Found {len(point_coords)} Point elements. These were replaced with 'points' attribute in 2013-07-15.")
        score -= 10
    
    return score

def _check_2015_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2015-07-15 version."""
    # Check for confidence values outside 0.0-1.0 range (bug fixed in 2015)
    text_equivs = root.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}TextEquiv")
    if not text_equivs:
        text_equivs = root.findall(".//TextEquiv")
    
    invalid_conf_count = 0
    for te in text_equivs:
        conf = te.get("conf")
        if conf:
            try:
                conf_val = float(conf)
                if conf_val < 0.0 or conf_val > 1.0:
                    invalid_conf_count += 1
            except ValueError:
                invalid_conf_count += 1
    
    if invalid_conf_count > 0:
        warnings.append(f"Found {invalid_conf_count} TextEquiv elements with confidence values outside 0.0-1.0 range. These will be valid in 2015-07-15.")
        score -= 5
    
    return score

def _check_2016_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2016-07-15 version."""
    # Check for old Chinese script values that need migration
    script_attrs = []
    for elem in root.iter():
        for attr in ["primaryScript", "secondaryScript", "script"]:
            if attr in elem.attrib:
                script_attrs.append((elem.tag, attr, elem.attrib[attr]))
    
    old_chinese_scripts = ["Chinese-Traditional", "Chinese-Simplified"]
    migration_needed = []
    for tag, attr, value in script_attrs:
        if value in old_chinese_scripts:
            migration_needed.append(f"{tag}@{attr}='{value}'")
    
    if migration_needed:
        warnings.append(f"Found {len(migration_needed)} elements with old Chinese script values that need migration to ISO 15924 format: {', '.join(migration_needed[:5])}")
        score -= 15
    
    return score

def _check_2017_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2017-07-15 version."""
    # Check for multiple TextEquiv elements (introduced in 2017)
    text_equivs = root.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}TextEquiv")
    if not text_equivs:
        text_equivs = root.findall(".//TextEquiv")
    
    multiple_equiv_count = 0
    for parent in text_equivs:
        if len(parent.getparent().findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}TextEquiv")) > 1:
            multiple_equiv_count += 1
    
    if multiple_equiv_count > 0:
        warnings.append(f"Found {multiple_equiv_count} elements with multiple TextEquiv children. This feature was introduced in 2017-07-15.")
        score -= 5
    
    return score

def _check_2018_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2018-07-15 version."""
    # Check for old Relation structure (changed in 2018)
    old_relations = root.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}Relation")
    if not old_relations:
        old_relations = root.findall(".//Relation")
    
    for rel in old_relations:
        region_refs = rel.findall(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}RegionRef")
        if not region_refs:
            region_refs = rel.findall(".//RegionRef")
        
        if len(region_refs) == 2:
            warnings.append("Found Relation elements with 2 RegionRef children. In 2018-07-15, these should be SourceRegionRef and TargetRegionRef.")
            score -= 10
            break
    
    return score

def _check_2019_compatibility(root, warnings: List[str], errors: List[str], score: int) -> int:
    """Check compatibility issues for 2019-07-15 version."""
    # Check for Page-level TextStyle (introduced in 2019)
    page_elem = root.find(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}Page")
    if not page_elem:
        page_elem = root.find(".//Page")
    
    if page_elem is not None:
        text_style = page_elem.find(".//{http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15}TextStyle")
        if not text_style:
            text_style = page_elem.find(".//TextStyle")
        
        if text_style is not None:
            warnings.append("Found Page-level TextStyle element. This feature was introduced in 2019-07-15.")
            score -= 5
    
    return score