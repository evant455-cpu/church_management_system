from django.db import migrations

# See module_system_mechanics_schema.md "Database-level backstop": this
# guards against a future bug or a direct database edit bypassing the
# application-layer cascade in services.disable_module() -- it should
# never fire in normal operation, since that function always disables
# dependents before the prerequisite within the same transaction.

FORWARD_SQL = """
CREATE OR REPLACE FUNCTION check_module_dependency_consistency()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.is_enabled = false AND OLD.is_enabled = true THEN
    IF EXISTS (
      SELECT 1
      FROM congregation_modules cm
      JOIN module_dependencies md ON md.module_id = cm.module_id
      WHERE cm.congregation_id = NEW.congregation_id
        AND md.depends_on_module_id = NEW.module_id
        AND cm.is_enabled = true
    ) THEN
      RAISE EXCEPTION
        'Cannot disable module id % for congregation id % while a dependent module is still enabled',
        NEW.module_id, NEW.congregation_id;
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_module_dependency_consistency
BEFORE UPDATE ON congregation_modules
FOR EACH ROW
EXECUTE FUNCTION check_module_dependency_consistency();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS enforce_module_dependency_consistency ON congregation_modules;
DROP FUNCTION IF EXISTS check_module_dependency_consistency();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("module_system", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD_SQL, reverse_sql=REVERSE_SQL),
    ]
