import streamlit as st
from pageplus.gui.utils.guideline_editor_utils import GuidelineManager


def profile_editor_view():
    st.header("Guideline Profile Editor")

    tab1, tab2, tab3 = st.tabs(["Evaluate", "Mapping", "Missing Unicodes"])

    with tab1:
        st.write("Manage evaluation profiles and their rules.")
        evaluate_manager = GuidelineManager(profile_type="rules")

        # --- Profile Management ---
        col1, col2 = st.columns([2, 1])
        
        with col1:
            profile_names = evaluate_manager.get_profile_names()
            selected_profile = st.selectbox("Select Profile", [""] + profile_names, key="evaluate_profile_select")

        with col2:
            new_profile_name = st.text_input("Create New Profile", key="evaluate_new_profile_name")
            if st.button("Create", key="evaluate_create_profile"):
                if new_profile_name and new_profile_name not in profile_names:
                    evaluate_manager.create_profile(new_profile_name)
                    evaluate_manager.save_data()
                    st.success(f"Profile '{new_profile_name}' created!")
                    st.session_state.evaluate_new_profile_name = ""  # Clear input
                    st.rerun()
                else:
                    st.error("Profile name is invalid or already exists.")

        if not selected_profile:
            st.info("Please select or create a profile to continue.")
        else:
                   
            st.markdown("---")
            st.subheader(f"Editing Profile: {selected_profile}")

            rule_type = st.radio(
                "Select Rule Category to Edit",
                ["forbidden", "exception"],
                key="rule_type_selection",
                horizontal=True
            )

            st.markdown("---")
            st.write(f"**Manage '{rule_type.capitalize()}' Rules in Profile**")
            profile_data = evaluate_manager.get_profile(selected_profile)
        
            all_rules_of_type = evaluate_manager.get_rule_names_by_type(rule_type)
            profile_rules_of_type = profile_data.get("rules", {}).get(rule_type, [])

            updated_rules = st.multiselect(
                f"Select {rule_type.capitalize()} Rules",
                all_rules_of_type,
                default=profile_rules_of_type,
                key=f"{selected_profile}_{rule_type}_rules"
            )
            
            st.markdown("---")

            # --- Rule Definition ---
            st.write(f"**Define or Edit a '{rule_type.capitalize()}' Rule**")
        
            rule_names = [""] + evaluate_manager.get_rule_names_by_type(rule_type)
            selected_rule_name = st.selectbox("Select Existing Rule to Edit", rule_names, key=f"select_rule_{rule_type}")
            new_rule_name = st.text_input("Or Create New Rule Name", key=f"new_rule_name_{rule_type}")
        
            rule_name_to_edit = new_rule_name if new_rule_name else selected_rule_name

            # Initialize or reset session state for rule sources
            if 'rule_sources' not in st.session_state:
                st.session_state.rule_sources = []
                st.session_state.current_rule = None
                st.session_state.current_rule_type = None

            if (rule_name_to_edit and st.session_state.get('current_rule') != rule_name_to_edit) or \
               (st.session_state.get('current_rule_type') != rule_type):
            
                st.session_state.rule_sources = []
                if rule_name_to_edit:
                    rule_data = evaluate_manager.get_rule(rule_name_to_edit)
                    sources = rule_data.get("sources", [])
                    for source in sources:
                        for category, values in source.items():
                            if isinstance(values, list):
                                for value in values:
                                    st.session_state.rule_sources.append({"category": category, "value": value})
                            else:
                                st.session_state.rule_sources.append({"category": category, "value": values})
            
                st.session_state.current_rule = rule_name_to_edit
                st.session_state.current_rule_type = rule_type

            st.write("**Rule Sources**")
        
            rule_categories = ["Hex", "Codepoint", "Glyph", "Name (Exact)", "Name (Contains)", "Regex"]
        
            for i, source_item in enumerate(st.session_state.rule_sources):
                cols = st.columns([3, 3, 1])
                
                current_category_key = source_item.get("category", "hex")
                current_category_display = current_category_key.capitalize()
                current_value = source_item.get("value", "")
                
                with cols[0]:
                    category = st.selectbox(
                        "Source Category",
                        options=rule_categories,
                        index=rule_categories.index(current_category_display) if current_category_display in rule_categories else 0,
                        key=f"category_{i}"
                    )
                with cols[1]:
                    value = st.text_input(
                        "Source Value",
                        value=current_value,
                        key=f"value_{i}"
                    )
                with cols[2]:
                    if st.button("➖", key=f"remove_source_{i}"):
                        st.session_state.rule_sources.pop(i)
                        st.rerun()
                
                category_key = category.lower().split(' ')[0]
                st.session_state.rule_sources[i] = {"category": category_key, "value": value}

            if st.button("➕ Add Source", key="evaluate_add_source"):
                st.session_state.rule_sources.append({"category": "hex", "value": ""})
                st.rerun()

            if st.button("Save Rule", key="evaluate_save_rule"):
                if rule_name_to_edit:
                    grouped_sources = {}
                    for source_item in st.session_state.rule_sources:
                        category = source_item["category"]
                        value = source_item["value"]
                        if category not in grouped_sources:
                            grouped_sources[category] = []
                        grouped_sources[category].append(value)
                
                    final_sources = []
                    for category, values in grouped_sources.items():
                        if category == "regex":
                            for value in values:
                                final_sources.append({category: value})
                        else:
                            final_sources.append({category: values})

                    evaluate_manager.add_rule_definition(rule_name_to_edit, final_sources, rule_type)
                    evaluate_manager.add_rule_to_profile(selected_profile, rule_type, rule_name_to_edit)
                    evaluate_manager.save_data()
                    st.success(f"Rule '{rule_name_to_edit}' saved as '{rule_type}'.")
                    st.session_state.rule_sources = []
                    st.session_state.current_rule = None
                    st.rerun()
                else:
                    st.warning("Please select or create a rule to save.")
                
            st.markdown("---")
            version_input = st.text_input("Rule Version", key="evaluate_version_input")
            if st.button("Set Version", key="evaluate_set_version"):
                if rule_name_to_edit and version_input:
                    evaluate_manager.set_rule_version(rule_name_to_edit, version_input)
                    evaluate_manager.save_data()
                    st.success(f"Version for rule '{rule_name_to_edit}' set to '{version_input}'.")
                else:
                    st.warning("Please enter a rule name and a version.")

            if st.button(f"Update Profile's {rule_type.capitalize()} Rules", key="evaluate_update_profile_rules"):
                other_rule_type = "exception" if rule_type == "forbidden" else "forbidden"
                other_rules = profile_data.get("rules", {}).get(other_rule_type, [])

                if rule_type == "forbidden":
                    evaluate_manager.update_profile_rules(selected_profile, forbidden_rules=updated_rules, exception_rules=other_rules)
                else:
                    evaluate_manager.update_profile_rules(selected_profile, forbidden_rules=other_rules, exception_rules=updated_rules)
                    
                evaluate_manager.save_data()
                st.success(f"Profile '{selected_profile}' updated successfully.")
                st.rerun()

    with tab2:
        st.write("Manage mapping profiles and their 'from-to' glyph mapping rules.")
        mapping_manager = GuidelineManager(profile_type="mappings")

        # --- Profile Management ---
        col1_map, col2_map = st.columns([2, 1])
        with col1_map:
            map_profile_names = mapping_manager.get_profile_names()
            selected_map_profile = st.selectbox("Select Profile", [""] + map_profile_names, key="mapping_profile_select")
        with col2_map:
            new_map_profile_name = st.text_input("Create New Profile", key="mapping_new_profile_name")
            if st.button("Create", key="mapping_create_profile"):
                if new_map_profile_name and new_map_profile_name not in map_profile_names:
                    mapping_manager.create_profile(new_map_profile_name)
                    mapping_manager.save_data()
                    st.success(f"Profile '{new_map_profile_name}' created!")
                    st.session_state.mapping_new_profile_name = ""
                    st.rerun()
                else:
                    st.error("Profile name is invalid or already exists.")

        if not selected_map_profile:
            st.info("Please select or create a mapping profile to continue.")
        else:
            st.markdown("---")
            st.subheader(f"Editing Mapping Profile: {selected_map_profile}")

            map_rule_type_display = st.radio(
                "Select Rule Category to Edit",
                ["deterministic", "non-deterministic"],
                key="map_rule_type_selection",
                horizontal=True
            )
            map_rule_type = map_rule_type_display

            st.markdown("---")
            st.write(f"**Manage '{map_rule_type_display.capitalize()}' Rules in Profile**")
            map_profile_data = mapping_manager.get_profile(selected_map_profile)

            all_map_rules = mapping_manager.get_rule_names_by_type(map_rule_type)
            profile_map_rules = map_profile_data.get("rules", {}).get(map_rule_type, [])

            updated_map_rules = st.multiselect(
                f"Select {map_rule_type_display.capitalize()} Rules",
                all_map_rules,
                default=profile_map_rules,
                key=f"{selected_map_profile}_{map_rule_type}_rules"
            )

            # --- Rule Definition for Normalization ---
            st.write(f"**Define or Edit a '{map_rule_type_display.capitalize()}' Rule**")
            
            map_rule_names = [""] + mapping_manager.get_rule_names_by_type(map_rule_type)
            selected_map_rule = st.selectbox("Select Existing Rule to Edit", map_rule_names, key=f"select_map_rule_{map_rule_type}")
            new_map_rule_name = st.text_input("Or Create New Rule Name", key=f"new_map_rule_name_{map_rule_type}")
            
            map_rule_to_edit = new_map_rule_name if new_map_rule_name else selected_map_rule

            if 'map_rule_mappings' not in st.session_state:
                st.session_state.map_rule_mappings = []
                st.session_state.map_rule_mode = "glyph"

            if map_rule_to_edit and (st.session_state.get('current_map_rule') != map_rule_to_edit or st.session_state.get('current_map_rule_type') != map_rule_type):
                rule_data = mapping_manager.get_rule(map_rule_to_edit)
                st.session_state.map_rule_mappings = rule_data.get("mappings", [])
                st.session_state.map_rule_mode = rule_data.get("mode", "glyph")
                st.session_state.current_map_rule = map_rule_to_edit
                st.session_state.current_map_rule_type = map_rule_type

            mode = st.selectbox("Rule Mode", ["glyph", "regex"], index=["glyph", "regex"].index(st.session_state.map_rule_mode), key="map_rule_mode_select")
            st.session_state.map_rule_mode = mode

            st.write("**Glyph Mappings**")
            for i, mapping in enumerate(st.session_state.map_rule_mappings):
                cols = st.columns([2, 2, 1])
                from_glyph = cols[0].text_input("From", value=mapping.get("from", ""), key=f"map_from_{i}_{map_rule_type}")
                to_glyph = cols[1].text_input("To", value=mapping.get("to", ""), key=f"map_to_{i}_{map_rule_type}")
                if cols[2].button("➖", key=f"map_remove_{i}_{map_rule_type}"):
                    st.session_state.map_rule_mappings.pop(i)
                    st.rerun()
                st.session_state.map_rule_mappings[i] = {"from": from_glyph, "to": to_glyph}

            if st.button("➕ Add Mapping", key="map_add_mapping"):
                st.session_state.map_rule_mappings.append({"from": "", "to": ""})
                st.rerun()

            if st.button("Save Rule", key="map_save_rule"):
                if map_rule_to_edit:
                    rule_data_to_save = {
                        "mode": st.session_state.map_rule_mode,
                        "mappings": st.session_state.map_rule_mappings
                    }
                    mapping_manager.add_rule_definition(map_rule_to_edit, rule_data_to_save, map_rule_type)
                    mapping_manager.add_rule_to_profile(selected_map_profile, map_rule_type, map_rule_to_edit)
                    mapping_manager.save_data()
                    st.success(f"Mapping rule '{map_rule_to_edit}' saved.")
                    st.session_state.map_rule_mappings = []
                    st.session_state.current_map_rule = None
                    st.rerun()
                else:
                    st.warning("Please select or create a rule to save.")

            if st.button(f"Update Profile's {map_rule_type_display.capitalize()} Rules", key="mapping_update_profile_rules"):
                other_rule_type = "non-deterministic" if map_rule_type == "deterministic" else "deterministic"
                other_rules = map_profile_data.get("rules", {}).get(other_rule_type, [])

                if map_rule_type == "deterministic":
                    mapping_manager.update_normalization_profile_rules(
                        selected_map_profile,
                        normalize_rules=updated_map_rules,
                        denormalize_rules=other_rules
                    )
                else:
                    mapping_manager.update_normalization_profile_rules(
                        selected_map_profile,
                        normalize_rules=other_rules,
                        denormalize_rules=updated_map_rules
                    )
                mapping_manager.save_data()
                st.success(f"Profile '{selected_map_profile}' updated successfully.")
                st.rerun()

    with tab3:
        st.write("Manage profiles for checking missing Unicode characters.")
        missing_manager = GuidelineManager(profile_type="rules", filename="missing_unicode.json")

        # --- Profile Management ---
        col1_miss, col2_miss = st.columns([2, 1])
        with col1_miss:
            miss_profile_names = missing_manager.get_profile_names()
            selected_miss_profile = st.selectbox("Select Profile", [""] + miss_profile_names, key="missing_profile_select")
        with col2_miss:
            new_miss_profile_name = st.text_input("Create New Profile", key="missing_new_profile_name")
            if st.button("Create", key="missing_create_profile"):
                if new_miss_profile_name and new_miss_profile_name not in miss_profile_names:
                    missing_manager.create_profile(new_miss_profile_name)
                    missing_manager.save_data()
                    st.success(f"Profile '{new_miss_profile_name}' created!")
                    st.session_state.missing_new_profile_name = ""
                    st.rerun()
                else:
                    st.error("Profile name is invalid or already exists.")
        
        if not selected_miss_profile:
            st.info("Please select or create a profile to continue.")
        else:
            st.markdown("---")
            st.subheader(f"Editing Missing Unicodes Profile: {selected_miss_profile}")

            profile_data = missing_manager.get_profile(selected_miss_profile)
            rules = profile_data.get("rules", {})

            # Use a unique session state key for this tab's editor
            session_key = f"missing_rules_{selected_miss_profile}"

            if session_key not in st.session_state or st.session_state.get('current_missing_profile') != selected_miss_profile:
                # Unroll the rules into a flat list for editing
                st.session_state[session_key] = []
                for category, values in rules.items():
                    for value in values:
                        st.session_state[session_key].append({"category": category, "value": value})
                st.session_state['current_missing_profile'] = selected_miss_profile

            st.write("**Rules**")
            rule_categories = ["Glyph", "Hex", "Codepoint", "Name", "Name regex", "Block", "Property", "Script", "Combined glyph"]
            
            for i, rule in enumerate(st.session_state[session_key]):
                cols = st.columns([2, 3, 1])
                category = cols[0].selectbox("Category", rule_categories, index=rule_categories.index(rule['category']) if rule['category'] in rule_categories else 0, key=f"miss_cat_{i}")
                value = cols[1].text_input("Value", value=rule['value'], key=f"miss_val_{i}")
                if cols[2].button("➖", key=f"miss_rem_{i}"):
                    st.session_state[session_key].pop(i)
                    st.rerun()
                st.session_state[session_key][i] = {"category": category, "value": value}

            if st.button("➕ Add Rule", key="miss_add_rule"):
                st.session_state[session_key].append({"category": "Glyph", "value": ""})
                st.rerun()

            if st.button("Save Profile", key="miss_save_profile"):
                # Roll up the flat list back into the correct dictionary structure
                new_rules = {}
                for rule in st.session_state[session_key]:
                    cat = rule['category']
                    val = rule['value']
                    if cat not in new_rules:
                        new_rules[cat] = []
                    new_rules[cat].append(val)
                
                # Update the profile data
                missing_manager.data["profiles"][selected_miss_profile]["rules"] = new_rules
                missing_manager.save_data()
                st.success(f"Profile '{selected_miss_profile}' saved successfully.")
                st.rerun()
