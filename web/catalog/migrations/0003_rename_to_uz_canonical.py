from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_category_name_ru_category_name_uz_color_name_ru_and_more"),
    ]

    operations = [
        # Drop the old constraint before renaming its referenced columns.
        migrations.RemoveConstraint(
            model_name="location", name="unique_building_area",
        ),
        # The existing "name"/"building"/"area" columns hold English values:
        # rename them to the *_en slots instead of recreating them.
        migrations.RenameField(model_name="category", old_name="name", new_name="name_en"),
        migrations.RenameField(model_name="color", old_name="name", new_name="name_en"),
        migrations.RenameField(model_name="location", old_name="building", new_name="building_en"),
        migrations.RenameField(model_name="location", old_name="area", new_name="area_en"),
        # Make the uz columns canonical (non-blank, unique / constraint).
        migrations.AlterField(
            model_name="category",
            name="name_uz",
            field=models.CharField(max_length=50, unique=True),
        ),
        migrations.AlterField(
            model_name="category",
            name="name_en",
            field=models.CharField(max_length=50, blank=True),
        ),
        migrations.AlterField(
            model_name="color",
            name="name_uz",
            field=models.CharField(max_length=32, unique=True),
        ),
        migrations.AlterField(
            model_name="color",
            name="name_en",
            field=models.CharField(max_length=32, blank=True),
        ),
        migrations.AlterField(
            model_name="color",
            name="name_ru",
            field=models.CharField(max_length=32, blank=True),
        ),
        # Align Meta options with the new canonical fields.
        migrations.AlterModelOptions(
            name="category",
            options={"ordering": ["name_uz"]},
        ),
        migrations.AlterModelOptions(
            name="color",
            options={"ordering": ["name_uz"]},
        ),
        migrations.AlterModelOptions(
            name="location",
            options={"ordering": ["building_uz", "area_uz"]},
        ),
        migrations.AlterField(
            model_name="location",
            name="building_uz",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="location",
            name="building_en",
            field=models.CharField(max_length=100, blank=True),
        ),
        migrations.AlterField(
            model_name="location",
            name="area_uz",
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name="location",
            name="area_en",
            field=models.CharField(max_length=150, blank=True),
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(
                fields=("building_uz", "area_uz"), name="unique_building_area_uz",
            ),
        ),
    ]
