#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
PDF JavaScript Checker and Remover Tool

This script checks PDF files for embedded JavaScript and can optionally remove it,
saving a sanitized version of the file.

Requires the 'pikepdf' library: pip install pikepdf

Usage:
  # Check a single PDF for JavaScript
  python pdf_sanitizer.py check <input_pdf_path>
  # Check a single PDF for JavaScript (with verbose logging)
  python pdf_sanitizer.py -v check <input_pdf_path>

  # Remove JavaScript from a PDF and save to a new file
  python pdf_sanitizer.py remove <input_pdf_path> <output_pdf_path>
  # Remove JavaScript from a PDF (with verbose logging)
  python pdf_sanitizer.py -v remove <input_pdf_path> <output_pdf_path>

  # Get help
  python pdf_sanitizer.py -h
  python pdf_sanitizer.py check -h
  python pdf_sanitizer.py remove -h
"""

import pikepdf
import os
import logging
import argparse
import sys
from typing import Optional, Dict, List, Union, Any

# --- Global Configuration ---
# Setup basic logging - level can be adjusted by command-line args
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# Define type alias for PDF objects for clarity
PdfObject = Union[pikepdf.Dictionary, pikepdf.Array, pikepdf.Name, pikepdf.String, int, float, bool, type(None), pikepdf.Stream]


# --- Core Logic Functions (Slightly Modified Logging) ---

def contains_javascript(pdf_path: str) -> bool:
    """
    Checks if a PDF file potentially contains JavaScript actions.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        True if JavaScript is found, False otherwise.
        Returns False on errors like file not found or password protection.
    """
    if not os.path.exists(pdf_path):
        log.error(f"File not found: {pdf_path}")
        return False # Indicate error / inability to check

    log.info(f"Starting JavaScript check for: {pdf_path}")
    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            # Using a helper to avoid code duplication
            if _check_for_js_recursive(pdf.Root, set()):
                 log.warning(f"JavaScript found during recursive check in: {pdf_path}")
                 return True

            # Explicit checks for common top-level structures for clarity
            # 1. Check Document Level Actions (OpenAction)
            if pdf.Root.get('/OpenAction'):
                action = pdf.Root.get('/OpenAction')
                if _is_javascript_action(action):
                    log.warning(f"Found JavaScript in Document OpenAction: {pdf_path}")
                    return True

            # 2. Check Document-Level JavaScript Name Tree
            if pdf.Root.get('/Names') and pdf.Root.Names.get('/JavaScript'):
                log.warning(f"Found JavaScript in Document Names Tree: {pdf_path}")
                return True

            # 3. Check Page Level Actions and Annotations
            for i, page in enumerate(pdf.pages):
                # Check Page Actions (Open/Close)
                if page.get('/AA'):
                    page_actions = page.get('/AA')
                    if isinstance(page_actions, pikepdf.Dictionary):
                        for action_type in [pikepdf.Name('/O'), pikepdf.Name('/C')]: # Page Open, Page Close
                             action = page_actions.get(action_type)
                             if _is_javascript_action(action):
                                log.warning(f"Found JavaScript in Page {i+1} Action ({action_type}): {pdf_path}")
                                return True

                # Check Annotations Actions
                annotations = page.get('/Annots', []) # Default to empty list if /Annots is missing
                if isinstance(annotations, pikepdf.Array):
                    for annot_ref in annotations:
                        annot = annot_ref # Use the reference directly
                        if isinstance(annot, pikepdf.Dictionary):
                            # Check simple Action (/A)
                            action = annot.get('/A') # Get the action object
                            if _is_javascript_action(action):
                                log.warning(f"Found JavaScript in Annotation Action (Page {i+1}): {pdf_path}")
                                try:
                                    log.debug(f"Problematic Annotation Dict (Page {i+1}): {annot}")
                                    log.debug(f"Problematic Action Dict (/A): {action}")
                                except Exception as log_e:
                                    log.debug(f"Could not fully log annotation/action details: {log_e}")
                                return True

                            # Check Additional Actions (/AA)
                            aa_actions = annot.get('/AA')
                            if isinstance(aa_actions, pikepdf.Dictionary):
                                # Check common annotation action types
                                for action_key in [pikepdf.Name(k) for k in ['/E', '/X', '/D', '/U', '/Fo', '/Bl', '/PO', '/PC', '/PV', '/PI']]:
                                    action = aa_actions.get(action_key)
                                    if _is_javascript_action(action):
                                        log.warning(f"Found JavaScript in Annotation Additional Action ({action_key}, Page {i+1}): {pdf_path}")
                                        return True

    except pikepdf.PasswordError:
        log.error(f"PDF is password protected: {pdf_path}. Cannot check for JavaScript.")
        return False # Indicate error / inability to check
    except Exception as e:
        log.error(f"Error processing PDF {pdf_path} during check: {e}", exc_info=log.level <= logging.DEBUG)
        return False # Indicate error / inability to check

    log.info(f"No obvious JavaScript found in {pdf_path}")
    return False


def _is_javascript_action(action_obj: Optional[PdfObject]) -> bool:
    """Helper to check if a PDF object is a JavaScript action dictionary or array thereof."""
    if isinstance(action_obj, pikepdf.Dictionary):
        return action_obj.get('/S') == pikepdf.Name('/JavaScript')
    elif isinstance(action_obj, pikepdf.Array):
        # Check if any action in the array is JavaScript
        return any(_is_javascript_action(item) for item in action_obj)
    return False


def _check_for_js_recursive(obj: PdfObject, visited: set) -> bool:
    """Recursive helper for detection."""
    if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Array)):
        return False

    # Avoid infinite loops
    obj_id = None
    if hasattr(obj, 'objgen'):
        obj_id = obj.objgen
        if obj_id in visited:
            return False
        visited.add(obj_id)

    if isinstance(obj, pikepdf.Dictionary):
        if obj.get('/S') == pikepdf.Name('/JavaScript'):
            return True # The object itself is a JS action

        for key, value in obj.items():
             # Check actions directly
            if key in [pikepdf.Name('/A'), pikepdf.Name('/AA'), pikepdf.Name('/OpenAction')]:
                 if _is_javascript_action(value):
                     return True
            # Recurse
            if _check_for_js_recursive(value, visited):
                 return True

    elif isinstance(obj, pikepdf.Array):
        for item in obj:
            if _check_for_js_recursive(item, visited):
                return True

    return False


# --- JavaScript Removal Function ---

def _remove_js_recursive(obj: PdfObject, visited: set):
    """
    Recursively searches and removes JavaScript actions within PDF objects.
    Modifies the object in place. Returns True if changes were made.
    """
    if not isinstance(obj, (pikepdf.Dictionary, pikepdf.Array)):
        return False # No changes made

    # Avoid infinite loops with circular references
    obj_id = None
    made_changes = False
    if hasattr(obj, 'objgen'):
        obj_id = obj.objgen
        if obj_id in visited:
            log.debug(f"Skipping already visited object: {obj_id}")
            return False # Already processed
        visited.add(obj_id)

    if isinstance(obj, pikepdf.Dictionary):
        # No need for keys_to_delete for /A or /AA modifications now
        # Iterate over a copy of items for safe modification
        for key, value in list(obj.items()):
            action_removed_here = False # Prevents double recursion if handled specially

            # Check common Action Keys directly (/A, /OpenAction)
            if key in [pikepdf.Name('/A'), pikepdf.Name('/OpenAction')]:
                 if _is_javascript_action(value):
                    # --- Modification Start --- #
                    # Delete the key instead of assigning None
                    del obj[key] # Modify in place
                    # --- Modification End --- #
                    log.debug(f"Deleted key {key} (Direct JS Action) in object {obj_id}")
                    made_changes = True
                    action_removed_here = True # Don't recurse into the now deleted value's original reference

            # Handle /AA (Additional Actions Dictionary) specifically
            elif key == pikepdf.Name('/AA') and isinstance(value, pikepdf.Dictionary):
                modified_aa = False # Track if we changed anything inside /AA
                keys_to_delete_in_aa = [] # Collect keys to delete
                # Iterate inside the /AA dictionary
                for sub_key, sub_value in value.items(): # Iterate original
                    if _is_javascript_action(sub_value):
                         # --- Modification Start --- #
                         # Mark sub-key for deletion
                         keys_to_delete_in_aa.append(sub_key)
                         # --- Modification End --- #
                         log.debug(f"Marked sub-key {sub_key} for deletion within /AA dictionary in object {obj_id}")
                         made_changes = True
                         modified_aa = True # Flag that we modified /AA
                    else:
                        # Also recurse into non-JS actions within /AA if they are dicts/arrays
                         if _remove_js_recursive(sub_value, visited):
                             made_changes = True
                             modified_aa = True # Modification happened deeper

                # Delete marked keys after iteration
                for sub_key_to_delete in keys_to_delete_in_aa:
                     del value[sub_key_to_delete]
                     log.debug(f"Deleted sub-key {sub_key_to_delete} from /AA dictionary in object {obj_id}")

                # Optionally, remove the /AA key itself if it becomes empty after deletions
                if modified_aa and not value:
                    del obj[key]
                    log.debug(f"Deleted empty /AA dictionary in object {obj_id}")

            # Remove Document-Level JavaScript Name Tree (Deletion still appropriate here)
            elif key == pikepdf.Name('/Names') and isinstance(value, pikepdf.Dictionary):
                 js_tree = value.get('/JavaScript')
                 removed_js_tree = False
                 if js_tree is not None:
                    # --- Deletion Logic (remains the same) --- #
                    del value['/JavaScript']
                    log.info(f"Removed /JavaScript Name Tree from object {obj_id}")
                    made_changes = True
                    removed_js_tree = True
                 # --- End Deletion Logic --- #

                 # Still recurse into Names dict itself for other potential JS
                 # unless we just deleted the whole tree (value['/JavaScript'])?
                 # No, Names can contain other things, so always recurse.
                 if _remove_js_recursive(value, visited): made_changes = True
                 action_removed_here = True # Prevent double recursion below

            # If we didn't handle this key specifically above, recurse into its value
            if not action_removed_here:
                 if _remove_js_recursive(value, visited): made_changes = True

        # No top-level key deletions needed here anymore for /A or /AA

    elif isinstance(obj, pikepdf.Array):
        indices_to_delete = []
        # Iterate over indices for safe removal/modification
        for i in range(len(obj) - 1, -1, -1): # Iterate backwards
             item = obj[i]
             # Check if an item in an array is a direct reference to a JS Action
             if _is_javascript_action(item):
                 # --- Modification Start --- #
                 # Mark index for deletion
                 indices_to_delete.append(i)
                 # --- Modification End --- #
                 log.debug(f"Marked item at index {i} in Array for deletion (Direct JS Action)")
                 made_changes = True
             else:
                 # Recurse into array items if they are containers
                 if _remove_js_recursive(item, visited):
                     made_changes = True

        # Delete marked indices in reverse order to avoid index shifting issues
        if indices_to_delete:
            for i in sorted(indices_to_delete, reverse=True):
                del obj[i]
                log.debug(f"Deleted item at original index {i} from Array")

    # Clear visited status for this object ID *after* processing its children
    # This allows revisiting if reached via a different path (though unlikely with PDF structure)
    # if obj_id is not None and obj_id in visited:
    #     visited.remove(obj_id) # Reconsider if needed - might allow infinite loops if structure is weird

    return made_changes


def remove_javascript(pdf_path: str, output_path: str) -> bool:
    """
    Removes JavaScript actions from a PDF file and saves the sanitized version.

    Args:
        pdf_path: Path to the input PDF file.
        output_path: Path where the sanitized PDF will be saved.

    Returns:
        True if sanitization was successful and saved, False otherwise.
    """
    if not os.path.exists(pdf_path):
        log.error(f"Input file not found: {pdf_path}")
        return False
    if os.path.abspath(pdf_path) == os.path.abspath(output_path):
        log.error("Input and output paths cannot be the same for sanitization.")
        return False

    log.info(f"Starting JavaScript sanitization for: {pdf_path}")
    try:
        # allow_overwriting_input=True might be risky if input=output, handle separately if needed
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:

            # --- Multi-pass Removal Logic --- #
            total_changes_made = False
            max_passes = 10 # Safety limit
            for pass_num in range(max_passes):
                log.debug(f"Starting removal pass {pass_num + 1}")
                # Use a new visited set for each pass!
                visited_this_pass = set()
                made_changes_this_pass = False

                # 1. Process from the Root (for /OpenAction, /Names/JS, etc.)
                if _remove_js_recursive(pdf.Root, visited_this_pass):
                    made_changes_this_pass = True
                    log.debug(f"Changes detected from Root scan in pass {pass_num + 1}")

                # 2. Explicitly process Page Annotations
                log.debug(f"Explicitly scanning page annotations in pass {pass_num + 1}")
                for i, page in enumerate(pdf.pages):
                    # Check if page itself was visited by root scan, maybe redundant but safe?
                    page_obj_id = None
                    if hasattr(page, 'objgen'):
                        page_obj_id = page.objgen
                        # if page_obj_id in visited_this_pass: # Don't skip page processing based on root scan visit
                        #     log.debug(f"Page {i+1} (ID: {page_obj_id}) already visited by root scan, but processing annotations anyway.")
                        #     # We might need to process annotations even if page dict itself was visited
                        #     # Let _remove_js_recursive handle the visited check for the annotation itself
                        pass # Don't skip the whole page based on the visited set from the root scan

                    annotations = page.get('/Annots', None)
                    if isinstance(annotations, pikepdf.Array):
                        log.debug(f"Scanning {len(annotations)} annotations on Page {i+1} in pass {pass_num + 1}")
                        for j, annot_ref in enumerate(annotations):
                            # Recurse into each annotation individually
                            if _remove_js_recursive(annot_ref, visited_this_pass):
                                made_changes_this_pass = True
                                log.debug(f"Changes detected in annotation {j+1} on page {i+1} in pass {pass_num + 1}")
                    elif annotations is not None:
                         log.warning(f"Page {i+1} /Annots is not an Array: {type(annotations)}. Skipping direct annotation scan for this page.")

                if made_changes_this_pass:
                    log.info(f"Changes made during removal pass {pass_num + 1}")
                    total_changes_made = True
                else:
                    log.debug(f"No changes made during removal pass {pass_num + 1}, stopping.")
                    break # No changes in this pass, assume stable state
            else:
                # This else block executes if the loop completed without break (i.e., hit max_passes)
                log.warning(f"Removal process reached maximum passes ({max_passes}). Possible complex structure or loop. Saving current state.")
                total_changes_made = True # Assume changes were likely made if we hit the limit
            # --- End Multi-pass Logic --- #

            if total_changes_made:
                log.info("JavaScript elements potentially found and neutralized. Saving sanitized file.")
                # Save the modified PDF
                pdf.save(output_path)
                log.info(f"Sanitized PDF saved to: {output_path}")
            else:
                log.info("No JavaScript elements found or removed during sanitization process.")
                # Optionally save even if no changes, or skip save?
                # Current behaviour: Save anyway to produce the output file.
                pdf.save(output_path)
                log.info(f"Output PDF saved (no changes detected): {output_path}")

        return True

    except pikepdf.PasswordError:
        log.error(f"Failed to open password-protected PDF: {pdf_path}")
        return False
    except Exception as e:
        log.error(f"Error processing PDF {pdf_path} during remove: {e}", exc_info=log.level <= logging.DEBUG)
        return False


# --- Command Line Interface Setup ---

def main():
    parser = argparse.ArgumentParser(
        description="Check for and remove JavaScript from PDF files.",
        formatter_class=argparse.RawDescriptionHelpFormatter, # Preserve formatting in help
        epilog="Example usages:\n"
               "  python pdf_sanitizer.py check document.pdf\n"
               "  python pdf_sanitizer.py remove input.pdf output_sanitized.pdf --verbose\n"
    )

    # Add global verbose flag BEFORE subparsers
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging (DEBUG level).'
    )

    subparsers = parser.add_subparsers(dest='command', required=True, help='Action to perform')

    # --- 'check' command ---
    parser_check = subparsers.add_parser('check', help='Check a PDF file for JavaScript.')
    parser_check.add_argument(
        'input_pdf',
        type=str,
        help='Path to the input PDF file to check.'
    )

    # --- 'remove' command ---
    parser_remove = subparsers.add_parser('remove', help='Remove JavaScript from a PDF and save a sanitized version.')
    parser_remove.add_argument(
        'input_pdf',
        type=str,
        help='Path to the input PDF file to sanitize.'
    )
    parser_remove.add_argument(
        'output_pdf',
        type=str,
        help='Path to save the sanitized output PDF file.'
    )

    args = parser.parse_args()

    # Adjust logging level based on verbose flag
    if args.verbose:
        log.setLevel(logging.DEBUG)
        log.debug("Verbose logging enabled.")
        # Also update the root logger's handler if it exists
        for handler in logging.root.handlers:
            handler.setLevel(logging.DEBUG)


    # --- Execute Commands ---
    exit_code = 0
    if args.command == 'check':
        log.info(f"Executing 'check' command for: {args.input_pdf}")
        try:
            has_js = contains_javascript(args.input_pdf)
            if has_js:
                print(f"Result: JavaScript DETECTED in '{args.input_pdf}'.")
                # Optionally set exit_code = 1 here if needed downstream
            else:
                 # Check if the function returned False due to error or absence of JS
                 if not os.path.exists(args.input_pdf): # Check explicit errors first
                     print(f"Result: Cannot check '{args.input_pdf}'. File not found or inaccessible.")
                     exit_code = 2
                 else: # Assume absence of JS if file exists and no error logged previously
                     print(f"Result: No JavaScript detected (based on checks) in '{args.input_pdf}'.")
        except Exception as e:
            log.error(f"An unexpected error occurred during 'check': {e}", exc_info=log.level <= logging.DEBUG)
            print(f"Result: An error occurred while checking '{args.input_pdf}'. Check logs.")
            exit_code = 1

    elif args.command == 'remove':
        log.info(f"Executing 'remove' command for: {args.input_pdf} -> {args.output_pdf}")
        try:
            success = remove_javascript(args.input_pdf, args.output_pdf)
            if success:
                print(f"Result: Successfully processed '{args.input_pdf}' and saved sanitized file to '{args.output_pdf}'.")
                # Optional: Verify the output file
                log.info(f"Verifying sanitized file: {args.output_pdf}")
                if contains_javascript(args.output_pdf):
                    print(f"Verification Warning: JavaScript may still be present in '{args.output_pdf}'. Manual review recommended.")
                else:
                    print(f"Verification: Sanitized file '{args.output_pdf}' appears clean.")
            else:
                print(f"Result: Failed to sanitize '{args.input_pdf}'. Check logs for errors.")
                exit_code = 1 # Indicate failure
        except Exception as e:
            log.error(f"An unexpected error occurred during 'remove': {e}", exc_info=log.level <= logging.DEBUG)
            print(f"Result: An error occurred while sanitizing '{args.input_pdf}'. Check logs.")
            exit_code = 1

    sys.exit(exit_code)


# --- Main Entry Point ---
if __name__ == "__main__":
    main()
