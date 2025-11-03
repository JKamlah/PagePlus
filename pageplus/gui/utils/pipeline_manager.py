import json
import copy
from typing import Dict, List, Any, Optional
from pathlib import Path
from pageplus.utils.constants import GUI_STORAGE_DIR, PACKAGE_ROOT


class PipelineManager:
    """
    Handles loading, modifying, and saving Gemini pipeline configurations.
    
    Two-tier loading system with smart filtering:
    
    1. Default pipelines (System Stages: IDs 0001-1000)
       - Loaded from package storage (pageplus/gui/storage/gemini_pipelines.json)
       - Read-only, shipped with the application
       - Provide base stages that users can use immediately
    
    2. User pipelines (User Stages: IDs 1001+)
       - Loaded from user data directory (~/.local/share/PagePlus/storage/gemini/)
       - User-created stages, collections, and pipelines
       - User modifications to system stages (saved only if explicitly edited)
       - All saves go to user directory only
    
    Smart Save Behavior:
    - System stages (0001-1000) are NOT saved unless user explicitly edits them
    - User stages (1001+) are always saved
    - Modified system stages are saved to user directory
    - Keeps user config clean and focused on actual customizations
    
    The merged result is what users see and work with in the application.
    """

    def __init__(self):
        # Default pipelines location (in package, read-only)
        self.default_pipelines_path = PACKAGE_ROOT / "gui" / "storage" / "gemini_pipelines.json"
        
        # User pipelines location (in user data dir, read-write)
        self.user_storage_dir = GUI_STORAGE_DIR / "gemini"
        self.user_storage_dir.mkdir(parents=True, exist_ok=True)
        self.user_pipelines_path = self.user_storage_dir / "gemini_pipelines.json"
        
        self.data = self._load_data()

    def _load_data(self) -> Dict[str, Any]:
        """
        Loads pipeline data by:
        1. Loading default pipelines from package storage
        2. Loading user pipelines and merging/updating with defaults
        """
        # Start with default pipelines from package
        default_data = self._load_default_pipelines()
        
        # Load user-specific overrides/additions
        user_data = self._load_user_pipelines()
        
        # Merge: user data takes precedence, but defaults are kept
        merged_data = self._merge_pipeline_data(default_data, user_data)
        
        return merged_data
    
    def _load_default_pipelines(self) -> Dict[str, Any]:
        """Loads the default pipelines from the package storage directory."""
        if not self.default_pipelines_path.exists():
            return {
                "version": 1,
                "collections": {},
                "pipelines": {}
            }
        
        try:
            with open(self.default_pipelines_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migrate old terminology if needed
                if "groups" in data and "collections" not in data:
                    data["collections"] = data.pop("groups")
                if "presets" in data and "pipelines" not in data:
                    data["pipelines"] = data.pop("presets")
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "version": 1,
                "collections": {},
                "pipelines": {}
            }
    
    def _load_user_pipelines(self) -> Dict[str, Any]:
        """Loads user-specific pipeline overrides from the user data directory."""
        if not self.user_pipelines_path.exists():
            return {
                "version": 1,
                "collections": {},
                "pipelines": {}
            }
        
        try:
            with open(self.user_pipelines_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Migrate old terminology if needed
                if "groups" in data and "collections" not in data:
                    data["collections"] = data.pop("groups")
                if "presets" in data and "pipelines" not in data:
                    data["pipelines"] = data.pop("presets")
                return data
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                "version": 1,
                "collections": {},
                "pipelines": {}
            }
    
    def _merge_pipeline_data(self, default_data: Dict[str, Any], user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges default and user pipeline data.
        - Collections: User collections are added to defaults, user stages can override default stages by ID
        - Pipelines: User pipelines override default pipelines by name
        - If a stage ID exists in both user and default, ONLY the user version is kept (no duplicates)
        """
        merged = copy.deepcopy(default_data)
        
        # Build a global map of all user stage IDs to track overrides
        user_stage_ids = set()
        for coll_data in user_data.get("collections", {}).values():
            for stage in coll_data.get("stages", []):
                user_stage_ids.add(stage.get("id"))
        
        # First pass: Remove any default stages that are overridden by user stages
        for coll_name in merged.get("collections", {}):
            original_stages = merged["collections"][coll_name].get("stages", [])
            # Keep only stages that are NOT overridden by user
            merged["collections"][coll_name]["stages"] = [
                s for s in original_stages if s.get("id") not in user_stage_ids
            ]
        
        # Second pass: Merge user collections and stages
        user_collections = user_data.get("collections", {})
        for coll_name, coll_data in user_collections.items():
            if coll_name in merged["collections"]:
                # Collection exists in both: add user stages (defaults already filtered)
                merged["collections"][coll_name]["stages"].extend(coll_data.get("stages", []))
                # Update description if provided by user
                if coll_data.get("description"):
                    merged["collections"][coll_name]["description"] = coll_data["description"]
            else:
                # New user collection
                merged["collections"][coll_name] = copy.deepcopy(coll_data)
        
        # Merge pipelines (user pipelines override defaults by name)
        user_pipelines = user_data.get("pipelines", {})
        merged["pipelines"].update(user_pipelines)
        
        # Use latest version number
        merged["version"] = max(default_data.get("version", 1), user_data.get("version", 1))
        
        return merged

    def _is_system_stage_id(self, stage_id: str) -> bool:
        """
        Checks if a stage ID is a system stage (0001-1000).
        System stages should only be saved if explicitly modified by the user.
        """
        try:
            stage_num = int(stage_id)
            return 1 <= stage_num <= 1000
        except (ValueError, TypeError):
            return False
    
    def _get_next_user_stage_id(self) -> str:
        """
        Generates the next available user stage ID.
        User stages start at 1001 and increment.
        Returns a 4-digit zero-padded string (e.g., "1001", "1002", etc.)
        """
        max_id = 1000  # Start from 1001
        
        # Check all collections for the highest numeric ID
        for coll_data in self.data.get("collections", {}).values():
            for stage in coll_data.get("stages", []):
                try:
                    stage_num = int(stage.get("id", "0"))
                    if stage_num > max_id:
                        max_id = stage_num
                except (ValueError, TypeError):
                    pass
        
        # Return next ID as 4-digit string
        next_id = max_id + 1
        return f"{next_id:04d}"
    
    def _filter_user_data(self) -> Dict[str, Any]:
        """
        Filters the current data to only include user-specific modifications.
        System stages (IDs 0001-1000) are excluded unless they differ from defaults.
        """
        # Load current defaults to compare
        default_data = self._load_default_pipelines()
        default_stages_by_id = {}
        
        # Build a lookup of all default stages by ID
        for coll_name, coll_data in default_data.get("collections", {}).items():
            for stage in coll_data.get("stages", []):
                default_stages_by_id[stage["id"]] = {
                    "collection": coll_name,
                    "stage": stage
                }
        
        # Create filtered user data
        user_data = {
            "version": self.data.get("version", 1),
            "collections": {},
            "pipelines": copy.deepcopy(self.data.get("pipelines", {}))
        }
        
        # Process each collection
        for coll_name, coll_data in self.data.get("collections", {}).items():
            user_stages = []
            
            for stage in coll_data.get("stages", []):
                stage_id = stage.get("id")
                
                # Check if this is a system stage
                if self._is_system_stage_id(stage_id):
                    # Only save if modified or moved to different collection
                    if stage_id in default_stages_by_id:
                        default_stage_info = default_stages_by_id[stage_id]
                        default_stage = default_stage_info["stage"]
                        default_coll = default_stage_info["collection"]
                        
                        # Save if stage was modified or moved to different collection
                        if stage != default_stage or coll_name != default_coll:
                            user_stages.append(stage)
                    else:
                        # System ID but not in defaults? Save it (shouldn't happen)
                        user_stages.append(stage)
                else:
                    # Non-system stage (user-created), always save
                    user_stages.append(stage)
            
            # Only include collection if it has user stages or doesn't exist in defaults
            if user_stages or coll_name not in default_data.get("collections", {}):
                user_data["collections"][coll_name] = {
                    "description": coll_data.get("description", ""),
                    "stages": user_stages
                }
        
        return user_data
    
    def save_data(self) -> None:
        """
        Saves the pipeline data to the user's pipelines file.
        Only user modifications are saved:
        - System stages (IDs 0001-1000) are excluded unless explicitly modified
        - User-created stages (IDs > 1000 or non-numeric) are always saved
        - All pipelines are saved
        - User-created collections are saved
        """
        user_data = self._filter_user_data()
        
        with open(self.user_pipelines_path, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, indent=4, ensure_ascii=False)

    # ===== COLLECTION OPERATIONS =====

    def get_collection_names(self) -> List[str]:
        """Returns a list of all collection names."""
        return list(self.data.get("collections", {}).keys())

    def create_collection(self, name: str, description: str = "") -> bool:
        """Creates a new collection."""
        if name in self.get_collection_names():
            return False  # Collection already exists

        if "collections" not in self.data:
            self.data["collections"] = {}
        
        self.data["collections"][name] = {
            "description": description,
            "stages": []
        }
        return True

    def get_collection(self, name: str) -> Dict[str, Any]:
        """Returns the data for a specific collection."""
        return self.data.get("collections", {}).get(name, {"description": "", "stages": []})

    def update_collection_description(self, name: str, description: str) -> bool:
        """Updates a collection's description."""
        if name not in self.get_collection_names():
            return False
        
        self.data["collections"][name]["description"] = description
        return True

    def delete_collection(self, name: str) -> bool:
        """Deletes a collection and all its stages."""
        if name not in self.get_collection_names():
            return False
        
        del self.data["collections"][name]
        return True

    # ===== STAGE OPERATIONS =====

    def get_stages_in_collection(self, collection_name: str) -> List[Dict[str, Any]]:
        """Returns all stages in a specific collection."""
        collection = self.get_collection(collection_name)
        return collection.get("stages", [])

    def get_stage_by_id(self, collection_name: str, stage_id: str) -> Optional[Dict[str, Any]]:
        """Returns a specific stage by its ID."""
        stages = self.get_stages_in_collection(collection_name)
        for stage in stages:
            if stage.get("id") == stage_id:
                return stage
        return None

    def add_stage(
        self,
        collection_name: str,
        name: str,
        category: str,
        stage_type: str,
        system_prompt: str = "",
        user_prompt: str = "<|input|>\\n",
        attributes: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Adds a new stage to a collection. Returns the stage ID or None if failed.
        New user stages get IDs starting from 1001.
        """
        if collection_name not in self.get_collection_names():
            return None

        stage_id = self._get_next_user_stage_id()
        stage = {
            "id": stage_id,
            "name": name,
            "category": category,
            "type": stage_type,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "attributes": attributes or {},
            "filters": filters or {}
        }

        self.data["collections"][collection_name]["stages"].append(stage)
        return stage_id

    def update_stage(
        self,
        collection_name: str,
        stage_id: str,
        name: Optional[str] = None,
        category: Optional[str] = None,
        stage_type: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        attributes: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Updates an existing stage."""
        stages = self.get_stages_in_collection(collection_name)
        
        for stage in stages:
            if stage.get("id") == stage_id:
                if name is not None:
                    stage["name"] = name
                if category is not None:
                    stage["category"] = category
                if stage_type is not None:
                    stage["type"] = stage_type
                if system_prompt is not None:
                    stage["system_prompt"] = system_prompt
                if user_prompt is not None:
                    stage["user_prompt"] = user_prompt
                if attributes is not None:
                    stage["attributes"] = attributes
                if filters is not None:
                    stage["filters"] = filters
                return True
        
        return False

    def delete_stage(self, collection_name: str, stage_id: str) -> bool:
        """Deletes a stage from a collection."""
        if collection_name not in self.get_collection_names():
            return False

        stages = self.data["collections"][collection_name]["stages"]
        for i, stage in enumerate(stages):
            if stage.get("id") == stage_id:
                del stages[i]
                return True
        
        return False

    def get_stages_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Returns all stages of a specific category across all collections."""
        stages = []
        for collection_name in self.get_collection_names():
            collection_stages = self.get_stages_in_collection(collection_name)
            for stage in collection_stages:
                if stage.get("category") == category:
                    stages.append({
                        **stage,
                        "collection": collection_name
                    })
        return stages

    # ===== PIPELINE OPERATIONS =====

    def get_pipeline_names(self) -> List[str]:
        """Returns a list of all pipeline names."""
        return list(self.data.get("pipelines", {}).keys())

    def get_pipelines_by_category(self, category: str) -> List[str]:
        """Returns pipeline names filtered by category."""
        pipelines = []
        for name, pipeline in self.data.get("pipelines", {}).items():
            if pipeline.get("category") == category:
                pipelines.append(name)
        return pipelines

    def create_pipeline(
        self,
        name: str,
        category: str,
        description: str = "",
        stages: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """Creates a new pipeline."""
        if name in self.get_pipeline_names():
            return False  # Pipeline already exists

        if "pipelines" not in self.data:
            self.data["pipelines"] = {}

        self.data["pipelines"][name] = {
            "description": description,
            "category": category,
            "stages": stages or []
        }
        return True

    def get_pipeline(self, name: str) -> Dict[str, Any]:
        """Returns the data for a specific pipeline."""
        pipeline = self.data.get("pipelines", {}).get(name, {
            "description": "",
            "category": "OCR",
            "stages": []
        })
        # Support old "pipeline" key, migrate to "stages"
        if "pipeline" in pipeline and "stages" not in pipeline:
            pipeline["stages"] = pipeline.pop("pipeline")
        return pipeline

    def update_pipeline(
        self,
        name: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        stages: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """Updates an existing pipeline."""
        if name not in self.get_pipeline_names():
            return False

        pipeline = self.data["pipelines"][name]
        if description is not None:
            pipeline["description"] = description
        if category is not None:
            pipeline["category"] = category
        if stages is not None:
            pipeline["stages"] = stages
        
        return True

    def delete_pipeline(self, name: str) -> bool:
        """Deletes a pipeline."""
        if name not in self.get_pipeline_names():
            return False
        
        del self.data["pipelines"][name]
        return True

    def add_stage_to_pipeline(
        self,
        pipeline_name: str,
        collection_name: str,
        stage_id: str,
        attributes: Optional[Dict[str, Any]] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Adds a stage reference to a pipeline."""
        if pipeline_name not in self.get_pipeline_names():
            return False

        stage_ref = {
            "collection": collection_name,
            "stage_id": stage_id,
            "attributes": attributes or {},
            "filters": filters or {}
        }

        pipeline = self.data["pipelines"][pipeline_name]
        if "stages" not in pipeline:
            pipeline["stages"] = []
        pipeline["stages"].append(stage_ref)
        return True

    def remove_stage_from_pipeline(self, pipeline_name: str, index: int) -> bool:
        """Removes a stage from a pipeline by index."""
        if pipeline_name not in self.get_pipeline_names():
            return False

        pipeline = self.data["pipelines"][pipeline_name]
        stages = pipeline.get("stages", [])
        if 0 <= index < len(stages):
            del stages[index]
            return True
        
        return False

    def reorder_pipeline_stages(self, pipeline_name: str, old_index: int, new_index: int) -> bool:
        """Reorders stages in a pipeline."""
        if pipeline_name not in self.get_pipeline_names():
            return False

        pipeline = self.data["pipelines"][pipeline_name]
        stages = pipeline.get("stages", [])
        if 0 <= old_index < len(stages) and 0 <= new_index < len(stages):
            stage = stages.pop(old_index)
            stages.insert(new_index, stage)
            return True
        
        return False

    # ===== MIGRATION UTILITIES =====

    def migrate_from_old_templates(self, old_templates_path: Path) -> bool:
        """Migrates old gemini_pp_templates.json to new pipeline format."""
        try:
            with open(old_templates_path, 'r', encoding='utf-8') as f:
                old_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return False

        # Create a default collection for migrated templates
        default_collection = "Migrated Templates"
        self.create_collection(default_collection, "Templates migrated from old format")

        # Migrate OCR templates
        if "OCR" in old_data and "system" in old_data["OCR"]:
            for prompt_name, prompt_text in old_data["OCR"]["system"].items():
                stage_id = self.add_stage(
                    collection_name=default_collection,
                    name=f"OCR - {prompt_name}",
                    category="OCR",
                    stage_type="All-in-One",
                    system_prompt=prompt_text,
                    user_prompt=old_data["OCR"].get("user", {}).get("Standard", "<|input|>\\n")
                )
                
                # Create a pipeline for this stage
                if stage_id:
                    self.create_pipeline(
                        name=f"OCR - {prompt_name}",
                        category="OCR",
                        description=f"Migrated from old template: {prompt_name}",
                        stages=[{
                            "collection": default_collection,
                            "stage_id": stage_id,
                            "attributes": {},
                            "filters": {}
                        }]
                    )

        # Migrate ReOCR templates
        if "ReOCR" in old_data and "system" in old_data["ReOCR"]:
            for prompt_name, prompt_text in old_data["ReOCR"]["system"].items():
                stage_id = self.add_stage(
                    collection_name=default_collection,
                    name=f"ReOCR - {prompt_name}",
                    category="ReOCR",
                    stage_type="Text Recognition",
                    system_prompt=prompt_text,
                    user_prompt=old_data["ReOCR"].get("user", {}).get("Standard", "<|input|>\\n"),
                    filters={"update_elements": ["Text", "Tags"]}
                )
                
                # Create a pipeline for this stage
                if stage_id:
                    self.create_pipeline(
                        name=f"ReOCR - {prompt_name}",
                        category="ReOCR",
                        description=f"Migrated from old template: {prompt_name}",
                        stages=[{
                            "collection": default_collection,
                            "stage_id": stage_id,
                            "attributes": {},
                            "filters": {}
                        }]
                    )

        self.save_data()
        return True

    # ===== EXPORT/IMPORT =====

    def export_pipeline(self, pipeline_name: str) -> Optional[Dict[str, Any]]:
        """Exports a pipeline with full stage details for sharing."""
        pipeline = self.get_pipeline(pipeline_name)
        if not pipeline or not pipeline.get("stages"):
            return None

        export_data = {
            "pipeline_name": pipeline_name,
            "description": pipeline.get("description", ""),
            "category": pipeline.get("category", "OCR"),
            "stages": []
        }

        for stage_ref in pipeline.get("stages", []):
            collection_name = stage_ref.get("collection")
            stage_id = stage_ref.get("stage_id")
            stage = self.get_stage_by_id(collection_name, stage_id)
            
            if stage:
                export_data["stages"].append({
                    "stage": copy.deepcopy(stage),
                    "override_attributes": stage_ref.get("attributes", {}),
                    "override_filters": stage_ref.get("filters", {})
                })

        return export_data

    def import_pipeline(self, export_data: Dict[str, Any], target_collection: Optional[str] = None) -> bool:
        """Imports a pipeline from exported data."""
        pipeline_name = export_data.get("pipeline_name")
        if not pipeline_name:
            return False

        # Create target collection if needed
        if target_collection is None:
            target_collection = "Imported Pipelines"
        
        if target_collection not in self.get_collection_names():
            self.create_collection(target_collection, "Collection for imported pipelines")

        # Import stages
        stages = []
        for item in export_data.get("stages", []):
            stage_data = item.get("stage", {})
            
            # Create stage in target collection
            stage_id = self.add_stage(
                collection_name=target_collection,
                name=stage_data.get("name", "Imported Stage"),
                category=stage_data.get("category", "OCR"),
                stage_type=stage_data.get("type", "All-in-One"),
                system_prompt=stage_data.get("system_prompt", ""),
                user_prompt=stage_data.get("user_prompt", "<|input|>\\n"),
                attributes=stage_data.get("attributes", {}),
                filters=stage_data.get("filters", {})
            )

            if stage_id:
                stages.append({
                    "collection": target_collection,
                    "stage_id": stage_id,
                    "attributes": item.get("override_attributes", {}),
                    "filters": item.get("override_filters", {})
                })

        # Create the pipeline
        return self.create_pipeline(
            name=pipeline_name,
            category=export_data.get("category", "OCR"),
            description=export_data.get("description", ""),
            stages=stages
        )

