from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, List, Any

import lxml.etree as ET
import numpy as np
import shapely
from shapely import affinity, concave_hull
from shapely.errors import TopologicalError, GEOSException
from shapely.geometry import LineString, LinearRing, Polygon, Point, MultiPoint, MultiLineString
from shapely.ops import nearest_points, unary_union

from pageplus.io.logger import logging
from pageplus.models.basic_elements import Region, CoordElement


@dataclass
class TextRegion(Region):
    parent: Optional[None] = field(default_factory=Any)  # Page object
    textlines: Optional[List[Textline]] = field(default_factory=list)

    def __post_init__(self):
        self.textlines = [Textline(e, self.ns, parent=self) for e in self.xml_element.iter(f"{{{self.ns}}}TextLine")]

    def counter(self, level: str = "textlines") -> int:
        """
        Counts elements at different levels in the text region (textlines, words, glyphs).
        """
        if not self.textlines:
            return 0

        if level == "textlines":
            return len(self.textlines)
        if level == "words":
            return sum(len(line.get_text().split()) for line in self.textlines if not line.is_text_empty())
        if level == "glyphs":
            return sum(len(line.get_text()) for line in self.textlines if not line.is_text_empty())

        return 0

    def delete_textlines(self, idx_list: list):
        """
        Deletes textlines from the region based on a list of indices.
        """
        for idx in sorted(idx_list, reverse=True):
            self.textlines[idx].xml_element.getparent().remove(self.textlines[idx].xml_element)
            self.textlines.pop(idx)

    def sort_baselines(self, mode: str = 'single_col'):
        """
        Sorts baselines in the text region.
        Currently, only 'single_col' mode, left to right and top to bottom is implemented.
        """
        if mode != 'single_col':
            return  # Currently only 'single_col' mode is implemented

        # Initial sorting by y-coordinate of the baseline
        sorted_textlines = []
        for idx, textline in enumerate(self.textlines):
            bl = textline.get_baseline_coordinates(returntype="linestring")
            if bl is None:
                bl = Polygon(textline._compute_baseline())
            if bl is None: continue
            sorted_textlines.append((idx, bl.centroid, bl))
        sorted_textlines = sorted(sorted_textlines, key=lambda x: x[1].y)

        # More complex sorting considering the proximity of lines and their horizontal positions
        for i in range(len(sorted_textlines) - 1):
            for j in range(i + 1, len(sorted_textlines)):
                line1, line2 = sorted_textlines[i][2], sorted_textlines[j][2]
                if self._baselines_near_same_height(line1, line2):
                    logging.info(
                        f"RO-Lineheight: In textregion {self.get_id()} the lines {self.textlines[sorted_textlines[i][0]].get_id()} ({self.textlines[sorted_textlines[i][0]].get_text()}) and {self.textlines[sorted_textlines[j][0]].get_id()} ({self.textlines[sorted_textlines[j][0]].get_text()}) at the same height")
                    if self._should_swap_baselines(line1, line2):
                        logging.info(
                            f"RO-Lineswap: In textregion {self.get_id()} the lines {self.textlines[sorted_textlines[i][0]].get_id()} and {self.textlines[sorted_textlines[j][0]].get_id()} got swapped.")
                    sorted_textlines[i], sorted_textlines[j] = sorted_textlines[j], sorted_textlines[i]

        # Apply the final sorting
        new_sorting = [idx for idx, _ in sorted_textlines]
        if new_sorting != sorted(new_sorting):
            self.textlines = [self.textlines[idx] for idx in new_sorting]
            for textline in self.textlines:
                self.xml_element.remove(textline.xml_element)
                self.xml_element.append(textline.xml_element)

    def _baselines_near_same_height(self, line1: LineString, line2: LineString, tolerance='5') -> bool:
        """ Helper function to check if two lines are near the same height """
        # Calculate the distance between two centroids
        distance_cd = line1.centroid.x - line2.centroid.x
        line2 = affinity.translate(line2, x=distance_cd)
        return line1.buffer(distance=tolerance).intersects(line2.buffer(distance=tolerance))

    def _should_swap_baselines(self, line1: LineString, line2: LineString) -> bool:
        """ Helper function to determine if two lines should be swapped based on their horizontal positions """
        return line2.bounds[0] < line1.bounds[2]

    def sort_lines(self, mode: str = 'single_col'):
        """
        Sorts text lines based on their vertical positions and adjusts for lines that are horizontally misaligned.
        Currently, only 'single_col' mode is implemented.
        """
        if mode != 'single_col':
            return  # Other modes are not implemented

        # Sorting after y coordinates
        orig_sorted_textlines = [(idx, textline.get_coordinates(returntype="linearring").minimum_rotated_rectangle)
                                 for idx, textline in enumerate(self.textlines)]
        sorted_textlines = sorted(orig_sorted_textlines, key=lambda x: x[1].centroid.y)

        # More complex sorting considering the proximity of lines and their horizontal positions
        for i in range(len(sorted_textlines) - 1):
            for j in range(i + 1, len(sorted_textlines)):
                # TODO: Chech this behavior
                if len(sorted_textlines[i]) < 3 or len(sorted_textlines[j]) < 3: continue
                line1, line2 = sorted_textlines[i][2], sorted_textlines[j][2]
                if self._textlines_near_same_height(line1, line2):
                    logging.info(
                        f"RO-Lineheight: In textregion {self.get_id()} the lines {self.textlines[sorted_textlines[i][0]].get_id()} ({self.textlines[sorted_textlines[i][0]].get_text()}) and {self.textlines[sorted_textlines[j][0]].get_id()} ({self.textlines[sorted_textlines[j][0]].get_text()}) at the same height")
                    if self._should_swap_textlines(line1, line2):
                        logging.info(
                            f"RO-Lineswap: In textregion {self.get_id()} the lines {self.textlines[sorted_textlines[i][0]].get_id()} and {self.textlines[sorted_textlines[j][0]].get_id()} got swapped.")
                    sorted_textlines[i], sorted_textlines[j] = sorted_textlines[j], sorted_textlines[i]

    def _textlines_near_same_height(self, line1: Polygon, line2: Polygon) -> bool:
        """ Helper function to check if two lines are near the same height """
        # Align the centroids and check if one centroid is in the other polygon
        distance_cd = line1.centroid.x - line2.centroid.x
        line2 = affinity.translate(line2, x=distance_cd)
        if not line1.intersects(line2):
            return False
        return line2.contains(line1.centroid) or line1.contains(line2.centroid)

    def _should_swap_textlines(self, line1: LineString, line2: LineString) -> bool:
        """ Helper function to determine if two lines should be swapped based on their horizontal positions """
        return line2.bounds[0] < line1.bounds[2]

    def merge_splitted_lines(self, max_x_diff: int = 64, max_y_diff: int = 12):
        """
        Merges text lines that are close to each other based on x and y difference thresholds.
        """

        baseline_tuples = [line.get_baseline_coordinates(returntype="tuple") for line in self.textlines]

        i = 1
        while i < len(self.textlines):
            current_baseline = baseline_tuples[i]
            previous_baseline = baseline_tuples[i - 1]

            if self._can_merge_lines(current_baseline, previous_baseline, max_x_diff, max_y_diff):
                try:
                    new_polygon, new_baseline = self._merge_line_polygons_and_baselines(i, previous_baseline,
                                                                                        current_baseline)
                    self.textlines[i].update_coordinates(new_polygon.exterior, inputtype="polygon")
                    self.textlines[i].update_baseline_coords(new_baseline)
                    self.textlines[i].update_text(f"{self.textlines[i - 1].get_text()} {self.textlines[i].get_text()}")
                    self.delete_textlines([i - 1])
                    baseline_tuples[i] = new_baseline
                    baseline_tuples.pop(i - 1)
                except GEOSException:
                    logging.warning(
                        f"A conflict occurred while merging lines {self.textlines[i - 1].get_id()} and {self.textlines[i].get_id()}")
                    i += 1
                    continue
            else:
                i += 1

    def _can_merge_lines(self, current_baseline, previous_baseline, max_x_diff, max_y_diff):
        """
        Determines if two lines can be merged based on their baseline proximity.
        """
        if not current_baseline or not previous_baseline:
            return False
        return abs(previous_baseline[-1][0] - current_baseline[0][0]) <= max_x_diff and \
            abs(previous_baseline[-1][1] - current_baseline[0][1]) <= max_y_diff

    def _merge_line_polygons_and_baselines(self, line_index, previous_baseline, current_baseline):
        """
        Merges the polygons and baselines of two lines.
        """
        widths = [LineString([c1, c2]).length for line in self.textlines[line_index - 1:line_index + 1]
                  for c1, c2 in
                  zip(line.get_coordinates(returntype='polygon').minimum_rotated_rectangle.exterior.coords[:-1],
                      line.get_coordinates(returntype='polygon').minimum_rotated_rectangle.exterior.coords[1:])]
        mean_width = np.median(widths)
        polygon_to_polygon_bridge = self._calculate_bridge_region(previous_baseline,
                                                                  self.textlines[line_index - 1].get_coordinates(
                                                                      'tuple'),
                                                                  current_baseline,
                                                                  self.textlines[line_index].get_coordinates('tuple'),
                                                                  mean_width)
        new_polygon = self._unify_polygons(line_index, polygon_to_polygon_bridge)
        new_baseline = previous_baseline + current_baseline
        return new_polygon, new_baseline

    def _calculate_bridge_region(self, previous_baseline, previous_textline, current_baseline, current_textline,
                                 mean_width):
        """
        Calculates a bridge region between two polygons based on their baselines and mean width.
        """
        # Calculate a region between the two regions
        bridge_coords = [tuple for tuple in previous_textline if
                         tuple[0] > previous_baseline[-1][0] - int(mean_width * 0.75)] + \
                        [tuple for tuple in current_textline if
                         tuple[0] < current_baseline[0][0] + int(mean_width * 0.75)]
        return concave_hull(Polygon(bridge_coords), ratio=1.0)

    def _unify_polygons(self, line_index, bridge_polygon):
        """
        Unifies the polygons of two text lines including the bridge polygon.
        """
        previous_polygon = self.textlines[line_index - 1].get_coordinates(returntype='polygon')
        current_polygon = self.textlines[line_index].get_coordinates(returntype='polygon')
        return unary_union([previous_polygon, bridge_polygon, current_polygon])

    def split_region_by_textlinecoords(self, col: int = 2, center_mode: tuple = (3, (0, 2)), padding_region: int = 12,
                                       min_mean_grp_distance: int = 500, substract_small_from_big: bool = True) -> list:
        """ Split a region by finding a mean value dividing the textlines """
        regions = [defaultdict(list) for _ in range(col)]
        textline_polygons = [line.get_coordinates("polygon") for line in self.textlines]
        x_center_textlines = [int(poly.centroid.x) for poly in textline_polygons]

        if len(x_center_textlines) < center_mode[0]:
            return []

        x_center_grps = np.array_split(np.array(sorted(x_center_textlines)), center_mode[0])
        x_mean_grps = [np.mean(x_center_grps[idx]) for idx in center_mode[1]]

        if len(x_mean_grps) < 1 or (len(x_mean_grps) > 1 and x_mean_grps[1] - x_mean_grps[0] < min_mean_grp_distance):
            return []

        x_mean = int(np.mean(x_mean_grps))
        for idx, x_center_textline in enumerate(x_center_textlines):
            regions[x_center_textline < x_mean]['textlines'].append(self.textlines[idx])
            regions[x_center_textline < x_mean]['coords'].extend(textline_polygons[idx].exterior.coords)

        for region in regions:
            region_polygon = Polygon(region['coords']).convex_hull
            region_polygon.buffer(padding_region, cap_style=3, join_style=3)
            region['region_linearring'].append(LinearRing(shapely.geometry.polygon.orient(region_polygon,
                                                                                          sign=1.0).exterior.coords))
            region['region_coordstr'].append(self.convert_coordinates_polygon_to_str(region['region_linearring'][0]))
        if substract_small_from_big and len(regions) == 2:
            regions = self._subtract_overlapping_areas(regions)
        return regions

    def _subtract_overlapping_areas(self, regions):
        """
        Subtracts overlapping areas between two regions.
        """
        big, small = (1, 0) if regions[0]['region_linearring'][0].minimum_rotated_rectangle.area < \
                               regions[1]['region_linearring'][0].minimum_rotated_rectangle.area else (0, 1)
        big_polygon, small_polygon = [Polygon(region['region_linearring'][0]) for region in
                                      (regions[big], regions[small])]
        difference = big_polygon.difference(small_polygon)

        if isinstance(difference, (Polygon, LinearRing)):
            regions[big]['region_linearring'][0] = difference.exterior if isinstance(difference,
                                                                                     Polygon) else difference
        elif isinstance(difference, MultiLineString):
            regions[big]['region_linearring'][0] = difference.convex_hull.exterior

        regions[big]['region_coordstr'][0] = self.convert_coordinates_tuples_to_str(
            regions[big]['region_linearring'][0].coords)
        return regions

    def contains_textline(self, id: str) -> bool:
        """
        Checks if the text region contains a text line with the specified ID.
        """
        return any(textline.get_id() == id for textline in self.textlines)


@dataclass
class Textline(CoordElement):
    baseline_polyline: Optional[list] = None
    orientation: Optional[str] = None
    parent: Optional[Region] = None

    # IO methods
    def get_baseline_coordinates(self, returntype: str = "string"):
        """
        Retrieves the baseline coordinates in various formats based on the 'returntype' parameter.
        Supported return types are 'string', 'tuple', 'points', 'linestring'.
        """
        valid_returntypes = ["string", "tuple", "points", "linestring"]
        if returntype not in valid_returntypes:
            return None
        baseline = self.xml_element.find(f'{{{self.ns}}}Baseline')
        if baseline is not None:
            if returntype == "string":
                return baseline.attrib['points']
            else:
                coord_tuples = self.convert_coordinates_str_to_tuples(baseline.attrib['points'])
                if returntype == "tuple":
                    return coord_tuples
                elif returntype == "points":
                    return MultiPoint(coord_tuples)
                else:
                    return LineString(coord_tuples)

    def update_baseline_coords(self, coords: list) -> None:
        """
        Updates the baseline coordinates of the element with the provided coordinates.
        """
        coords_string = self.convert_coordinates_tuples_to_str(coords)
        baseline = self.xml_element.find(f'{{{self.ns}}}Baseline')
        if baseline is not None:
            baseline.set('points', coords_string)
        else:
            ET.SubElement(self.xml_element, 'Baseline', {'points': coords_string})

    # Text methods
    def update_text(self, text: str, index: int = 0) -> None:
        """
        Updates the text of the element with the provided string at the specified index.
        """
        text_equivs = self.xml_element.findall(f"{{{self.ns}}}TextEquiv")
        for text_equiv in text_equivs:
            if str(text_equiv.attrib.get("index", 0)) == str(index):
                unicode_element = text_equiv.find(f"{{{self.ns}}}Unicode")
                if unicode_element is not None:
                    unicode_element.text = text

    # Gemometry methods
    def validate_baseline(self, update=False) -> bool:
        """
        Validates the baseline coordinates of the textline, updates them if necessary,
        and ensures they are within the textline polygon.
        """
        baseline_tuples = self.get_baseline_coordinates(returntype="tuple")
        if not baseline_tuples:
            logging.warning(f"{self.get_id()}: Missing baseline")
            return False

        # Remove adjacent duplicates
        baseline_tuples = [baseline_tuples[0]] + [x for idx, x in enumerate(baseline_tuples[1:]) if
                                                  x != baseline_tuples[idx]]
        if len(baseline_tuples) == 1:
            logging.warning(f"{self.get_id()}: Baseline has just one point")
            return False

        try:
            textline_polygon = self.get_coordinates(returntype="polygon")
            baseline_linestring = LineString(baseline_tuples)

            if not textline_polygon.intersects(baseline_linestring):
                logging.warning(f"{self.get_id()}: Baseline is outside of the textregion "
                                f"{self.get_parent_element().attrib['id']}.")
                return False

            new_baseline_tuples, pts_outside, pts_replaced = [], [], []
            for idx, point in enumerate(baseline_tuples):
                pt = Point(point)

                if not textline_polygon.covers(pt):
                    pts_outside.append(point)
                    if update:
                        pt_distance = textline_polygon.distance(pt)
                        pred_distance = Point(new_baseline_tuples[-1]).distance(pt) if new_baseline_tuples else float(
                            'inf')
                        succ_distance = Point(baseline_tuples[idx + 1]).distance(pt) if idx != len(
                            baseline_tuples) - 1 else float('inf')

                        # Replace with nearest point if it's closer than predecessor and successor
                        if pt_distance < pred_distance and pt_distance < succ_distance:
                            nearest_pt = nearest_points(pt, textline_polygon)[1]
                            pts_replaced.append([point, [int(nearest_pt.x), int(nearest_pt.y)]])
                            point = (int(nearest_pt.x), int(nearest_pt.y))
                        else:
                            pts_replaced.append([point, None])

                new_baseline_tuples.append(point)

            if pts_outside:
                logging.warning(f"{self.get_id()}: Some points of the baseline are outside of the textregion "
                                f"{self.get_parent_element().attrib['id']}. Points outside {pts_outside}")
                if not update:
                    return False
                else:
                    logging.warning(f"{self.get_id()}: Some points got deleted or replaced"
                                    f"{self.get_parent_element().attrib['id']}. Points outside {pts_replaced}")

        except TopologicalError:
            logging.warning(
                f"{self.get_id()}: Baseline or parentregion {self.get_parent_element().attrib['id']} is invalid.")
            return False
        if update:
            self.update_baseline_coords(baseline_tuples)
        return True

    def _compute_baseline(self) -> list:
        """
        Computes the baseline coordinates based on the textline polygon.
        """
        # get minimum bounding box
        textline = self.get_coordinates(returntype='polygon')
        bbox = textline.minimum_rotated_rectangle

        # If the minimum rotated rectangle is a line, it represents the baseline
        if isinstance(bbox, LineString):
            return list(bbox.coords)

        coords = list(bbox.exterior.coords)

        # Calculate the baseline as the midline between the two longest sides of the bounding box
        lines = sorted(sorted([LineString([c1, c2]) for c1, c2 in zip(coords[:-1], coords[1:])],
                              key=lambda x: x.length, reverse=False)[:2],
                       key=lambda x: round((x.xy[0][1] + x.xy[1][1]) / 2), reverse=False)
        baseline_tuples = [list(line.interpolate((line.length) / 2).coords)[0] for line in lines]
        return baseline_tuples

    @staticmethod
    def find_nearest_intersection_polygon_linestring(polygon: Polygon, line: LineString, poi: tuple) -> tuple:
        """
        Finds the nearest intersection point between a polygon and a linestring to a point of interest (poi).
        """
        intersections = polygon.intersection(line)
        if intersections.is_empty:
            return poi

        valid_geom_types = ['Point', 'MultiPoint', 'LineString']
        if intersections.geom_type in valid_geom_types:
            nearest_pts = nearest_points(Point(poi), intersections)
            return tuple(map(int, nearest_pts[1].coords[0]))

        try:
            closest_point = min([(Point(poi).distance(Point(geom.coords[0])), geom.coords[0])
                                 for geom in intersections.geoms], key=lambda x: x[0])[1]
            return tuple(map(int, closest_point))
        except:
            pass

        return poi

    def place_textlinepolygon_over_baseline(self, mode="x") -> None:
        """
        Places the textline polygon over the baseline.
        Currently, only horizontal mode ('x') is implemented.
        """
        textline_linearring = self.get_coordinates(returntype='linearring')
        baseline_linestring = self.get_baseline_coordinates(returntype='linestring')

        if textline_linearring is None or baseline_linestring is None:
            return

        if mode == "x":
            xoff = round(((baseline_linestring.bounds[0] - textline_linearring.bounds[0]) +
                          (baseline_linestring.bounds[2] - textline_linearring.bounds[2])) / 2)
            textline_linearring = self._translate(textline_linearring, xoff=xoff, yoff=0, zoff=0)
            self.update_coordinates(textline_linearring)

    def translate_textlinepolygon(self, xoff=0, yoff=0) -> None:
        """
        Translate the textline polygon by the specified x and y offsets.
        """
        textline_coords = self.get_coordinates(returntype='tuple')
        translate_coords = [(x + xoff, y + yoff) for x, y in textline_coords]
        self.update_coordinates(translate_coords, inputtype='tuple')

    def translate_baseline(self, xoff=0, yoff=0) -> None:
        """
        Translate the baseline by the specified x and y offsets.
        """
        baseline_coords = self.get_baseline_coordinates(returntype='tuple')
        translate_coords = [(x + xoff, y + yoff) for x, y in baseline_coords]
        self.update_baseline_coords(translate_coords)

    def compute_pseudotextlinepolygon(self, buffersize=1) -> None:
        """
        Recomputes the textline polygon based on the baseline, using a buffer around the baseline.
        """
        baseline_linestring = self.baseline_coords(returntype='linestring')
        if baseline_linestring:
            textline_linearring = baseline_linestring.buffer(buffersize).minimum_rotated_rectangle
            self.update_coords(textline_linearring)

    def extend_baseline(self, create_missing: bool = True) -> None:
        """
        Extends the baseline to the minimum and maximum x values of the textline bounding box.
        """
        textline_polygon = self.get_coordinates(returntype='polygon')
        baseline_linestring = self.get_baseline_coordinates(returntype='linestring')

        try:
            if baseline_linestring is None or not textline_polygon.intersects(baseline_linestring):
                if not create_missing and baseline_linestring is None:
                    return
                baseline_coords = self._compute_baseline()
            else:
                baseline_coords = self.get_baseline_coordinates(returntype='tuple')

            extended_baseline = [self.find_nearest_intersection_polygon_linestring(
                textline_polygon, LineString(((textline_polygon.bounds[0],
                                               baseline_coords[0][1]), baseline_coords[0])),
                (textline_polygon.bounds[0], baseline_coords[0][1]))]

            # Extend the baseline with intermediate points
            if baseline_coords[1:-1]:
                mr_textline_polygon = textline_polygon.minimum_rotated_rectangle
                extended_baseline.extend(
                    [coord for coord in baseline_coords[1:-1] if mr_textline_polygon.contains(Point(coord))])

            # Extend the last baseline coordinate to the maximum x value of the textline bounding box
            extended_baseline.append(self.find_nearest_intersection_polygon_linestring(textline_polygon,
                                                                                       LineString(
                                                                                           ((textline_polygon.bounds[2],
                                                                                             baseline_coords[-1][1]),
                                                                                            baseline_coords[-1])),
                                                                                       (textline_polygon.bounds[2],
                                                                                        baseline_coords[-1][1])))
            coords = [(int(x[0]), int(x[1])) for x in extended_baseline if len(x) > 1]
            if coords:
                self.update_baseline_coords(coords)
        except GEOSException:
            logging.warning(f"The baseline of textline {self.get_id()} could not be extended.")
