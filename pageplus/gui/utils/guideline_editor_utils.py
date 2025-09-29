import json
import copy
from typing import Dict, List, Any
from collections.abc import MutableMapping
from pageplus.utils.constants import GUIDELINES_DIR, GUI_STORAGE_DIR
from pageplus.utils.guidelines.lib.settings import load_profiles


def deep_update(d, u):
    """Recursively update a dictionary."""
    for k, v in u.items():
        if isinstance(v, MutableMapping):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


class GuidelineManager:
    """Handles loading, modifying, and saving evaluation guideline profiles."""

    def __init__(self, profile_type: str = "rules", filename: str = "guidelines.json"):
        filename = "mappings.json" if profile_type == "mappings" else filename
        self.default_profiles_dir = GUIDELINES_DIR / "profiles"
        self.user_profiles_dir = GUI_STORAGE_DIR / "guidelines" / "profiles"
        self.user_profiles_dir.mkdir(parents=True, exist_ok=True)

        self.default_guidelines_path = self.default_profiles_dir / filename
        self.user_guidelines_path = self.user_profiles_dir / filename

        self.default_data = self._load_default_data()
        self.user_data = self._load_user_data()
        self.data = self._merge_data()

    def _load_default_data(self) -> Dict[str, Any]:
        """Loads the default guidelines JSON file."""
        try:
            with open(self.default_guidelines_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": 1, "rules": {}, "profiles": {}}

    def _load_user_data(self) -> Dict[str, Any]:
        """Loads the user guidelines JSON file."""
        if not self.user_guidelines_path.exists():
            return {"version": 1, "rules": {}, "profiles": {}}
        try:
            with open(self.user_guidelines_path, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"version": 1, "rules": {}, "profiles": {}}

    def _merge_data(self) -> Dict[str, Any]:
        """Merges default and user data, with user data taking precedence."""
        merged_data = copy.deepcopy(self.default_data)
        # Use deep_update for rules to correctly merge nested rule types
        deep_update(merged_data.get("rules", {}), self.user_data.get("rules", {}))
        merged_data.get("profiles", {}).update(self.user_data.get("profiles", {}))
        return merged_data

    def save_data(self):
        """Saves the user data back to the user's guidelines JSON file."""
        with open(self.user_guidelines_path, 'w', encoding='utf-8') as f:
            json.dump(self.user_data, f, indent=4)
        load_profiles.cache_clear()
        self.data = self._merge_data()

    def get_profile_names(self) -> List[str]:
        """Returns a list of all profile names from the merged data."""
        return list(self.data.get("profiles", {}).keys())

    def create_profile(self, name: str) -> bool:
        """Creates a new, empty profile in the user data."""
        if name in self.get_profile_names():
            return False  # Profile already exists

        if "profiles" not in self.user_data:
            self.user_data["profiles"] = {}
        self.user_data["profiles"][name] = {"description": "New custom profile", "rules": {"forbidden": [], "exception": []}}
        self.data = self._merge_data()
        return True

    def get_profile(self, name: str) -> Dict[str, Any]:
        """Returns the data for a specific profile from the merged data."""
        return self.data.get("profiles", {}).get(name, {})

    def get_all_rule_names(self) -> List[str]:
        """Returns a list of all defined rule names across all types from the merged data."""
        all_rules = set()
        for rules_of_type in self.data.get("rules", {}).values():
            all_rules.update(rules_of_type.keys())
        return sorted(list(all_rules))

    def get_rule_names_by_type(self, rule_type: str) -> List[str]:
        """Returns a list of rule names for a specific type from the merged data."""
        return list(self.data.get("rules", {}).get(rule_type, {}).keys())

    def get_rule(self, rule_name: str) -> Dict[str, Any]:
        """Returns the data for a specific rule from the merged data."""
        for rules_of_type in self.data.get("rules", {}).values():
            if rule_name in rules_of_type:
                return rules_of_type[rule_name]
        return {}

    def add_rule_definition(self, rule_name: str, sources: List[Dict[str, Any]], rule_type: str):
        """Adds or updates a rule's definition in user_data."""
        if "rules" not in self.user_data:
            self.user_data["rules"] = {}
        if rule_type not in self.user_data["rules"]:
            self.user_data["rules"][rule_type] = {}
        self.user_data["rules"][rule_type][rule_name] = {"sources": sources}
        self.data = self._merge_data()

    def add_rule_to_profile(self, profile_name: str, rule_type: str, rule_name: str):
        """Adds a rule to a profile's specified rule type list in user_data."""
        if "profiles" not in self.user_data:
            self.user_data["profiles"] = {}
        if profile_name not in self.user_data["profiles"]:
            profile_to_copy = self.data.get("profiles", {}).get(profile_name)
            if profile_to_copy:
                self.user_data["profiles"][profile_name] = copy.deepcopy(profile_to_copy)
            else:
                return  # Should not happen

        user_profile = self.user_data["profiles"][profile_name]
        if rule_name not in user_profile.get("rules", {}).get(rule_type, []):
            user_profile.setdefault("rules", {}).setdefault(rule_type, []).append(rule_name)
        self.data = self._merge_data()

    def set_rule_version(self, rule_name: str, version: str):
        """Sets the version for a specific rule, creating it in user_data if needed."""
        target_rule_type = None
        for r_type, rules in self.data.get("rules", {}).items():
            if rule_name in rules:
                target_rule_type = r_type
                break
        if not target_rule_type:
            return

        if "rules" not in self.user_data:
            self.user_data["rules"] = {}
        if target_rule_type not in self.user_data["rules"]:
            self.user_data["rules"][target_rule_type] = {}
        if rule_name not in self.user_data["rules"][target_rule_type]:
            rule_to_copy = self.data.get("rules", {}).get(target_rule_type, {}).get(rule_name)
            if rule_to_copy:
                self.user_data["rules"][target_rule_type][rule_name] = copy.deepcopy(rule_to_copy)
            else:
                return

        self.user_data["rules"][target_rule_type][rule_name]["version"] = version
        self.data = self._merge_data()

    def update_profile_rules(self, profile_name: str, forbidden_rules: List[str], exception_rules: List[str]):
        """Updates rules for a given profile, creating it in user_data if it's a default."""
        if "profiles" not in self.user_data:
            self.user_data["profiles"] = {}

        if profile_name not in self.user_data["profiles"]:
            profile_to_copy = self.data.get("profiles", {}).get(profile_name)
            if profile_to_copy:
                self.user_data["profiles"][profile_name] = copy.deepcopy(profile_to_copy)

        user_profile = self.user_data["profiles"].get(profile_name)
        if user_profile:
            user_profile["rules"] = {
                "forbidden": forbidden_rules,
                "exception": exception_rules
            }
        self.data = self._merge_data()

    def add_value_to_rule(self, rule_name: str, source: Dict[str, Any]):
        """This method seems unused in the profile editor but is kept for potential future use."""
        pass
