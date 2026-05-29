import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

from jsonschema import Draft7Validator, ValidationError, validators

logger = logging.getLogger("volta-plan-api")


class ValidationError_Custom(Exception):
    """Custom exception for validation errors with detailed information."""

    def __init__(self, message: str, errors: List[Dict[str, Any]] = None):
        self.message = message
        self.errors = errors or []
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detail": self.message,
            "errors": self.errors,
        }


def load_schema(schema_path: str = "schemas/user_schema.json") -> Dict[str, Any]:
    """Load the user schema from JSON file."""
    try:
        path = Path(schema_path)
        if not path.exists():
            raise FileNotFoundError(f"Schema file not found: {schema_path}")

        with open(path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        logger.info(f"Schema loaded successfully from {schema_path}")
        return schema
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse schema JSON: {e}")
        raise
    except Exception as e:
        logger.error(f"Error loading schema: {e}")
        raise


def _get_required_fields(schema: Dict[str, Any], path: str = "") -> Dict[str, List[str]]:
    """
    Extract required fields from JSON schema recursively.
    Returns a dict mapping path to list of required field names.
    """
    required_by_path = {}

    if isinstance(schema, dict):
        if "properties" in schema and "required" in schema:
            required_by_path[path] = schema.get("required", [])

        # Recursively check nested properties
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                nested_path = f"{path}.{prop_name}" if path else prop_name
                nested_required = _get_required_fields(prop_schema, nested_path)
                required_by_path.update(nested_required)

    return required_by_path


def validate_user_input(
    user_data: Dict[str, Any],
    schema: Dict[str, Any] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Validate user input against the schema.

    Args:
        user_data: The user profile data to validate
        schema: The JSON schema to validate against (loads from file if None)

    Returns:
        Tuple of (is_valid, errors)
        - is_valid: True if validation passed
        - errors: List of error dictionaries with 'path', 'message', 'value'
    """
    if schema is None:
        schema = load_schema()

    errors: List[Dict[str, Any]] = []
    validator = Draft7Validator(schema)

    # Collect all validation errors
    for error in validator.iter_errors(user_data):
        error_path = list(error.absolute_path)
        error_dict = {
            "path": error_path,
            "path_str": ".".join(str(p) for p in error_path) or "root",
            "message": error.message,
            "validator": error.validator,
            "value": error.instance if not isinstance(error.instance, dict) else "<object>",
        }
        errors.append(error_dict)

    is_valid = len(errors) == 0
    return is_valid, errors


def check_missing_attributes(
    user_data: Dict[str, Any],
    schema: Dict[str, Any] = None,
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Check for missing required attributes in the user input.

    Args:
        user_data: The user profile data to validate
        schema: The JSON schema to validate against (loads from file if None)

    Returns:
        Tuple of (is_valid, missing_fields)
        - is_valid: True if all required fields are present
        - missing_fields: List of missing field dictionaries
    """
    if schema is None:
        schema = load_schema()

    missing_fields: List[Dict[str, Any]] = []

    def check_required_in_schema(
        data: Any,
        current_schema: Dict[str, Any],
        path: str = "",
    ) -> None:
        """Recursively check required fields."""
        if not isinstance(current_schema, dict):
            return

        properties = current_schema.get("properties", {})
        required_fields = current_schema.get("required", [])

        for field in required_fields:
            if isinstance(data, dict):
                if field not in data or data[field] is None:
                    full_path = f"{path}.{field}" if path else field
                    missing_fields.append({
                        "path": full_path,
                        "field": field,
                        "message": f"Missing required field: {full_path}",
                    })
            else:
                # If data is not a dict but schema expects properties, data is invalid
                full_path = f"{path}.{field}" if path else field
                missing_fields.append({
                    "path": full_path,
                    "field": field,
                    "message": f"Expected object but got {type(data).__name__} at {path}",
                })

        # Recursively check nested properties
        if isinstance(data, dict):
            for prop_name, prop_schema in properties.items():
                if prop_name in data and data[prop_name] is not None:
                    nested_path = f"{path}.{prop_name}" if path else prop_name
                    check_required_in_schema(data[prop_name], prop_schema, nested_path)

    check_required_in_schema(user_data, schema)

    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields


def validate_user_profile(user_data: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Comprehensive validation of user profile data.
    Combines schema validation and missing field checking.

    Args:
        user_data: The user profile data to validate

    Returns:
        Tuple of (is_valid, all_errors)
        - is_valid: True if all validations passed
        - all_errors: List of all errors found
    """
    logger.info("Starting user profile validation")

    schema = load_schema()

    # Check schema validation
    is_schema_valid, schema_errors = validate_user_input(user_data, schema)
    logger.info(f"Schema validation: {'passed' if is_schema_valid else 'failed'}")

    # Check for missing required fields
    is_complete, missing_fields = check_missing_attributes(user_data, schema)
    logger.info(f"Required fields check: {'passed' if is_complete else 'failed'}")

    # Combine errors
    all_errors = []

    if missing_fields:
        for error in missing_fields:
            all_errors.append({
                "type": "missing_field",
                **error,
            })

    if schema_errors:
        for error in schema_errors:
            all_errors.append({
                "type": "validation_error",
                **error,
            })

    is_valid = len(all_errors) == 0

    if not is_valid:
        logger.warning(
            f"User profile validation failed with {len(all_errors)} error(s)"
        )
    else:
        logger.info("User profile validation passed")

    return is_valid, all_errors


def format_validation_errors(errors: List[Dict[str, Any]]) -> str:
    """
    Format validation errors into a human-readable string.

    Args:
        errors: List of error dictionaries from validation functions

    Returns:
        Formatted error message string
    """
    if not errors:
        return "No errors"

    formatted_lines = ["Validation failed with the following errors:"]

    for idx, error in enumerate(errors, 1):
        error_type = error.get("type", "unknown")
        path = error.get("path_str") or error.get("path", "unknown")
        message = error.get("message", "Unknown error")

        formatted_lines.append(f"  {idx}. [{error_type}] {path}: {message}")

    return "\n".join(formatted_lines)
