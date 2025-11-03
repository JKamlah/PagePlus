"""
Migration utility to convert old gemini_pp_templates.json to new pipeline format.
"""
from pathlib import Path
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.utils.constants import GUI_STORAGE_DIR


def migrate_templates() -> bool:
    """
    Migrates old template format to new pipeline format.
    Returns True if migration was successful or already done.
    """
    # Path to old templates
    old_templates_path = Path(__file__).parent.parent / "storage" / "gemini_pp_templates.json"
    
    if not old_templates_path.exists():
        print("No old templates file found. Nothing to migrate.")
        return True
    
    # Initialize pipeline manager
    manager = PipelineManager()
    
    # Check if already migrated (look for migrated collection)
    if "Migrated Templates" in manager.get_collection_names():
        print("Templates already migrated.")
        return True
    
    print(f"Migrating templates from {old_templates_path}...")
    success = manager.migrate_from_old_templates(old_templates_path)
    
    if success:
        print("Migration successful!")
        print(f"Created {len(manager.get_stages_in_collection('Migrated Templates'))} stages")
        print(f"Created {len(manager.get_pipeline_names())} pipelines")
        
        # Optionally rename old file to .bak
        backup_path = old_templates_path.with_suffix('.json.bak')
        if not backup_path.exists():
            old_templates_path.rename(backup_path)
            print(f"Old templates backed up to {backup_path}")
    else:
        print("Migration failed.")
    
    return success


if __name__ == "__main__":
    migrate_templates()

