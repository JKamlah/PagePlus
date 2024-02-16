from __future__ import annotations

import re
from dataclasses import dataclass

import lxml.etree as ET
import shapely
from shapely import affinity, normalize, line_interpolate_point, remove_repeated_points, simplify, is_valid_reason
from shapely.errors import TopologicalError, EmptyPartError
from shapely.geometry import LineString, LinearRing, Polygon, Point, MultiPoint, MultiPolygon, GeometryCollection
from shapely.ops import nearest_points, unary_union, split

from pageplus.io.logger import logging


@dataclass
class CoordElement:
    """ Class to represent and modify coordinates element."""
    xml_element: ET._Element
    ns: str  # Namespace for the XML element
    parent: None

    # IO methods
    def get_id(self) -> str:
        """ Returns the ID attribute of the XML element. """
        return self.xml_element.attrib["id"]

    def get_parent_element(self) -> ET._Element:
        """ Returns the parent XML element. """
        return self.xml_element.getparent()

    def get_coordinates(self, returntype: str = "string"):
        """
        Retrieves coordinates in various formats based on the 'returntype' parameter.
        Supported return types are 'string', 'tuple', 'points', 'linearring', 'mrr', 'polygon'.
        """
        valid_types = ["string", "tuple", "points", "linearring", "mrr", "polygon"]
        if returntype not in valid_types:
            return None

        coords = self.xml_element.find(f"{{{self.ns}}}Coords")
        if coords is None:
            return None

        points = coords.attrib['points']
        if returntype == "string":
            return points

        coord_tuples = self.convert_coordinates_str_to_tuples(points)
        if returntype == "tuple":
            return coord_tuples
        if returntype == "points":
            return MultiPoint(coord_tuples)

        if len(coord_tuples) < 3:
            logging.warning(f"The region {self.get_id()} has less than 3 coords.")
            return None

        if returntype == "linearring":
            coord_tuples = self._ensure_closed_ring(coord_tuples)
            return LinearRing(coord_tuples) if len(coord_tuples) > 3 else Polygon(coord_tuples).exterior

        if returntype == "mrr":
            return Polygon(coord_tuples).minimum_rotated_rectangle

        return Polygon(coord_tuples)

    def _ensure_closed_ring(self, coord_tuples):
        """ Ensures that the list of coordinate tuples forms a closed ring. """
        return coord_tuples + [coord_tuples[0]] if coord_tuples[0] != coord_tuples[-1] else coord_tuples

    def update_coordinates(self, data, inputtype: str = "polygon"):
        """
        Updates the coordinates of the XML element with the provided 'data',
        formatted according to the 'inputtype'.
        """
        if inputtype == "polygon":
            coordstr = self.convert_coordinates_polygon_to_str(data)
        elif inputtype == "tuple":
            coordstr = self.convert_coordinates_tuples_to_str(data)
        elif inputtype == "string":
            coordstr = data
        else:
            return

        coordstr = " ".join(self._remove_adjacent_duplicates(coordstr.split(' ')))
        coords = self.xml_element.find(f'{{{self.ns}}}Coords')
        coords.set('points', coordstr)

        # Conversion methods

    @staticmethod
    def convert_coordinates_str_to_tuples(coordstr: str) -> list:
        """
        Converts a string of coordinates to a list of coordinate tuples (x, y).
        """
        coordstr_vals = re.split(r',|\s', coordstr)
        coordvals = list(map(int, map(float, coordstr_vals)))
        return list(zip(coordvals[0::2], coordvals[1::2]))

    @staticmethod
    def convert_coordinates_tuples_to_str(coords_tuples: list) -> str:
        """
        Converts a list of coordinate tuples (x, y) to a string representation.
        """
        return ' '.join([f"{int(x)},{int(y)}" for x, y in coords_tuples]).strip()

    @staticmethod
    def convert_coordinates_polygon_to_str(polygon: Polygon) -> str:
        """
        Converts a Polygon object to a string representation of its coordinates.
        """
        polygon = polygon.exterior if isinstance(polygon, Polygon) else polygon
        return ' '.join([f"{int(x)},{int(y)}" for x, y in polygon.coords]).strip() if polygon else ''

    # Text Methods
    def get_text(self):
        """ Retrieves the text content of the XML element. """
        text_equivs = self.xml_element.findall(f"{{{self.ns}}}TextEquiv")
        for text_equiv in text_equivs:
            if str(text_equiv.attrib.get("index", 0)) == "0":
                return "".join(text_equiv.find(f"{{{self.ns}}}Unicode").itertext())
        return None

    def is_text_empty(self) -> bool:
        """ Checks if the text content of the XML element is empty. """
        text = self.get_text()
        return text is None or text.strip() == ""

    def has_text(self) -> bool:
        """ Checks if the XML element has text content. """
        return self.get_text() is not None

    def validate_text(self) -> bool:
        """ Validates if the text content of the XML element is not empty. """
        if self.is_text_empty():
            logging.warning(f"{self.get_parent_element().attrib['id']}: Text is empty.")
            return False
        return True

    # Geometric Relationship Methods
    def within_parent(self) -> bool:
        """
        Checks if the current element is within its parent element.
        """
        try:
            polygon = self.get_coordinates(returntype="polygon")
            parent_polygon = self.parent.get_coordinates(returntype="polygon")
            return parent_polygon.contains(polygon)
        except Exception:
            return False

    def overlaps(self, polygon: Polygon, ratio: float = 0.3) -> bool:
        """
        Determines if the current element overlaps with the given polygon by a specified ratio.
        """
        try:
            textline_poly = self.get_coordinates(returntype="polygon")
            intersection_area = polygon.intersection(textline_poly).area
            return textline_poly.area * ratio < intersection_area
        except Exception:
            return False

    def validate_region(self) -> bool:
        """
        Validates the region by checking if the coordinates form a valid polygon and its relationship with the parent.
        """
        coord_tuples = self.get_coordinates(returntype="tuple")
        if not coord_tuples or len(coord_tuples) < 4:
            logging.warning(f"{self.get_id()}: Region is missing or has insufficient coord points.")
            return False

        region_polygon = LinearRing(coord_tuples)
        if not region_polygon.is_valid:
            reason = is_valid_reason(region_polygon)
            logging.warning(f"{self.get_id()}: Region is not valid. Error: {reason}")
            if 'Ring Self-intersection' in reason:
                logging.warning(f"We recommend to use the repair function to delete the self-intersection part.")
            return False

        parent_coords = self.get_parent_element().find(f"{{{self.ns}}}Coords")
        if parent_coords is not None:
            parent_coords_tuples = CoordElement.convert_coordinates_str_to_tuples(parent_coords.attrib['points'])
            if len(parent_coords_tuples) <= 2:
                logging.warning(
                    f"{self.get_parent_element().attrib['id']}: Parent region has insufficient coord points.")
                return False

            parent_polygon = Polygon(parent_coords_tuples)
            if not parent_polygon.is_valid or region_polygon.disjoint(parent_polygon):
                logging.warning(f"{self.get_id()}: Region is invalid or outside of the parent region.")
                return False

        return True

    # Geometric Modification Methods
    @staticmethod
    def _remove_adjacent_duplicates(lst):
        """ Removes adjacent duplicate elements from the list. """
        result = [lst[0]] + [lst[i] for i in range(1, len(lst)) if lst[i] != lst[i - 1]]
        # Check if the first and last item are the same (for closed shapes)
        if len(result) > 1 and result[0] == result[-1]:
            result.pop()
        return result

    @staticmethod
    def split_overlapping_linearrings(fst_lr: LinearRing, snd_lr: LinearRing) -> tuple[LinearRing, LinearRing]:
        """
        Splits two overlapping LinearRings into separate non-overlapping rings.
        """

        def centerline_linestrings(fst_ls: LineString, snd_ls: LineString) -> LineString:
            # Calculates a centerline between two LineStrings
            more_pts, less_pts = (fst_ls, snd_ls) if len(fst_ls.coords) > len(snd_ls.coords) else (snd_ls, fst_ls)
            centerline_pts = []
            for pt in more_pts.coords:
                pt = Point(pt)
                pt, nearest_pt = nearest_points(pt, less_pts)
                mid_pt = line_interpolate_point(LineString([pt, nearest_pt]), pt.distance(nearest_pt) / 2)
                centerline_pts.append(normalize(mid_pt))
            return LineString(centerline_pts)

        def centerlines_between_overlapping_linearrings(fst_lr: LinearRing, snd_lr: LinearRing) -> tuple[
            LineString, LineString]:
            # Determines centerlines between two overlapping LinearRings
            fst_ls, snd_ls = LineString(), LineString()
            if snd_lr.intersects(fst_lr) or not fst_lr.within(snd_lr):
                fst_ls = sorted([pt for pt in remove_repeated_points(fst_lr).coords if snd_lr.contains(Point(pt))],
                                key=lambda x: x[0])
                snd_ls = sorted([pt for pt in remove_repeated_points(snd_lr).coords if fst_lr.contains(Point(pt))],
                                key=lambda x: x[0])

                if not fst_ls or not snd_ls:
                    return LineString(), LineString()

                if len(fst_ls) > 1 or len(snd_ls) > 1:
                    fst_ls = fst_ls[:-1] if fst_ls[0] == fst_ls[-1] else fst_ls
                    snd_ls = snd_ls[:-1] if snd_ls[0] == snd_ls[-1] else snd_ls

                try:
                    centerline = centerline_linestrings(LineString(fst_ls), LineString(snd_ls))
                    fst_ls = LineString([fst_ls[0], *centerline.coords, fst_ls[-1]])
                    snd_ls = LineString([snd_ls[0], *centerline.coords, snd_ls[-1]])
                except:
                    return LineString(), LineString()

            return fst_ls, snd_ls

        fst_ls, snd_ls = centerlines_between_overlapping_linearrings(fst_lr, snd_lr)
        if fst_ls.is_empty or snd_ls.is_empty:
            return fst_lr, snd_lr

        fst_lr = sorted(split(Polygon(fst_lr), fst_ls).geoms, key=lambda x: x.area, reverse=True)[0].exterior
        snd_lr = sorted(split(Polygon(snd_lr), snd_ls).geoms, key=lambda x: x.area, reverse=True)[0].exterior

        return fst_lr, snd_lr

    @staticmethod
    def fit_first_into_second_linearring(fst_lr: LinearRing, snd_lr: LinearRing) -> LinearRing:
        """
        Fits the first LinearRing within the second one, adjusting it to fit inside.
        """
        if snd_lr.intersects(fst_lr) or not fst_lr.within(snd_lr):
            try:
                fst_poly = Polygon(fst_lr)
                snd_poly = Polygon(snd_lr)
                if not snd_poly.is_valid or not fst_poly.is_valid:
                    raise TopologicalError

                intersection = snd_poly.intersection(fst_poly)
                if intersection.is_empty:
                    raise EmptyPartError

                if intersection.geom_type == 'MultiPolygon':
                    intersection = max(intersection.geoms, key=lambda x: x.area)

                if intersection.geom_type == 'Polygon':
                    return intersection.exterior

            except (TopologicalError, EmptyPartError):
                # Handle error in geometry
                print("Could not find intersection!")
                pass
        return fst_lr

    def fit_into_parent(self, parent_coords=None):
        """
        Adjusts the current element to fit within its parent element.
        """
        coords = self.get_coordinates(returntype="linearring")

        if parent_coords is None or not isinstance(parent_coords, LinearRing):
            parent_element = self.get_parent_element().find(f"{{{self.ns}}}Coords")
            if parent_element is not None and parent_element.attrib['points'] != '0,0 0,0':
                parent_coords = Polygon(
                    CoordElement.convert_coordinates_str_to_tuples(parent_element.attrib['points'])).exterior
            else:
                return
        fitted_coords = CoordElement.fit_first_into_second_linearring(coords, parent_coords)
        self.update_coordinates(fitted_coords)

    def simplify(self, tolerance: int = 1):
        """
        Simplifies the coordinates of the element based on a tolerance value.
        """
        coords = self.get_coordinates(returntype="linearring")
        coords = simplify(coords, tolerance=tolerance)
        self.update_coordinates(coords)

    def convex_hull(self):
        """
        Updates the coordinates of the element to its convex hull.
        """
        coords = self.get_coordinates(returntype="polygon")
        convex_hull_coords = coords.convex_hull.exterior
        self.update_coordinates(convex_hull_coords)

    def remove_repeated_points(self, tolerance: int = 1):
        """
        Removes repeated points from the element's coordinates based on a tolerance value.
        """
        coords = self.get_coordinates(returntype="linearring")
        cleaned_coords = remove_repeated_points(coords, tolerance=tolerance)
        self.update_coordinates(cleaned_coords)

    def buffer(self, distance: int = 8, direction: str = "horizontal",
               simplify: bool = False, rectangle: bool = False) -> None:
        """
        Buffers the coordinates of the element based on specified parameters and updates the element.
        """
        coords = self.get_coordinates(returntype="linearring")
        buffered_coords = CoordElement._buffer(coords, distance, direction, simplify, rectangle)
        self.update_coordinates(buffered_coords)

    @staticmethod
    def _buffer(polygon: LinearRing, distance: int = 8,
                direction: str = "horizontal", simplify: bool = False, rectangle: bool = False) -> LinearRing:
        """
        Applies a buffer to a LinearRing and optionally modifies it based on specified parameters.
        """
        if distance != 0:
            padded_polygon = polygon.buffer(distance, cap_style="square", join_style="bevel")
        else:
            padded_polygon = polygon
        if direction in ["width", "horizontal"]:
            coords = affinity.scale(polygon.minimum_rotated_rectangle, xfact=0.9, yfact=0.9).exterior.coords
            lines = sorted([LineString([c1, c2]) for c1, c2 in zip(coords[:-1], coords[1:])],
                           key=lambda x: x.length if direction == "width" else abs(x.xy[0][0] - x.xy[0][1]),
                           reverse=False)
            scaled_lines = [affinity.scale(line, xfact=10, yfact=10, origin='centroid') for line in lines]
            upper_lower_bound = Polygon(list(scaled_lines[2].coords) + list(scaled_lines[3].coords))
            padded_polygon = padded_polygon.intersection(upper_lower_bound)
            if isinstance(padded_polygon, GeometryCollection):
                logging.warning(f"Cutting upper and lower bound produced multiple areas")
                return polygon
            extensions = [sorted(list(split(padded_polygon, line).geoms), key=lambda x: x.area, reverse=False)[0]
                          for line in scaled_lines[:2]]
            try:
                padded_polygon = unary_union(extensions + [Polygon(polygon)])
            except:
                return polygon
            padded_polygon = padded_polygon.convex_hull.exterior if \
                isinstance(padded_polygon, MultiPolygon) else padded_polygon.exterior

        if rectangle:
            return padded_polygon.minimum_rotated_rectangle

        if simplify:
            padded_polygon = padded_polygon.simplify(tolerance=0.95, preserve_topology=False)
        padded_polygon = padded_polygon.convex_hull if simplify else padded_polygon

        if not isinstance(padded_polygon, LinearRing):
            return LinearRing(shapely.geometry.polygon.orient(padded_polygon, sign=1.0).exterior.coords)
        else:
            return padded_polygon

    def translate(self, xoff: int = 0, yoff: int = 0, zoff: int = 0) -> None:
        """
        Translates the coordinates of the element.
        """
        tl = self.get_coordinates(returntype='linearring')
        tl = self._translate(tl, xoff=xoff, yoff=yoff, zoff=zoff)
        self.update_coordinates(tl, inputtype='polygon')

    @staticmethod
    def _translate(poly: Polygon, xoff: int = 0, yoff: int = 0, zoff: int = 0) -> Polygon:
        """
        Translates a LinearRing by specified x, y, and z offsets.
        """
        return affinity.translate(poly, xoff=xoff, yoff=yoff, zoff=zoff)


@dataclass
class Region(CoordElement):
    pass
