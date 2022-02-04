import ast
from json import load
import json
import os
import pickle
import time
import subprocess
from image_handling import (
    get_image_description,
)
from tools.converters import convert_coordinates
from tools.debug import check_file_type, p_e, p_i, p_line
from location_handler import (
    find_visible_coordinates_in_render,
    get_3d_location,
    find_visible_items_in_ds,
    get_raster_data,
)
from map_plotting import plot_to_map
from povs import primary_pov, debug_pov
from tools.texture import (
    create_route_texture,
    create_color_gradient_image,
)
from tools.file_handling import (
    get_mountain_data,
    read_image_locations,
    read_mountain_gpx,
)
from tools.types import CrsToLatLng, LatLngToCrs, Location


def render_dem(panorama_path, mode, mountains, render_filename):
    start_time = time.time()
    panorama_filename = panorama_path.split("/")[-1].split(".")[0]
    pov_filename = "/tmp/pov_file.pov"
    gpx_file = f"data/hikes/{panorama_filename}.gpx"

    render_settings_path = "render_settings.json"
    with open(render_settings_path) as json_file:
        data = load(json_file)
        dem_path = data["dem_path"]
        render_width = data["render_width"]
        render_height = data["render_height"]

        render_shape = [render_width, render_height]
        json_file.close()

    dem_path, original_dem, coordinates, viewing_direction = get_mountain_data(
        dem_path, panorama_path
    )
    if not dem_path:
        return False

    if mode == "debug":
        dem_path = original_dem

    if not check_file_type(dem_path):
        p_e("DEM file is not a valid GeoTIFF")
        return

    raster_data = get_raster_data(dem_path, coordinates)
    if not raster_data:
        return

    ds_name = original_dem.split("/")[-1].split(".")[0]

    if mode == "debug":
        debug_mode = 2  # 1 for hike route texture
        if debug_mode == 1:
            route_texture, texture_bounds = create_route_texture(
                dem_path, gpx_file, True
            )
        else:
            route_texture, texture_bounds = "", None
        with open(pov_filename, "w") as pf:
            pov = debug_pov(dem_path, route_texture, texture_bounds, raster_data[1][2])
            pf.write(pov)
            pf.close()
        params = [pov_filename, render_filename, [500, 500], "color"]
        execute_pov(params)
    else:
        if mode == 1:
            pov_mode = "depth"
            pov = primary_pov(dem_path, raster_data, mode=pov_mode)
            params = [pov_filename, render_filename, render_shape, pov_mode]
            with open(pov_filename, "w") as pf:
                pf.write(pov)
            pf.close()
            execute_pov(params)
        elif mode == 2:
            pov_mode = "height"
            pov = primary_pov(dem_path, raster_data, mode=pov_mode)
            params = [pov_filename, render_filename, render_shape, "color"]
            with open(pov_filename, "w") as pf:
                pf.write(pov)
            pf.close()
            execute_pov(params)
        elif mode == 3:
            pov_mode = "texture"
            gpx_exists = os.path.isfile("%s" % gpx_file)
            if gpx_exists:
                route_texture, texture_bounds = create_route_texture(dem_path, gpx_file)
                pov = primary_pov(
                    dem_path,
                    raster_data,
                    texture_path=route_texture,
                    tex_bounds=texture_bounds,
                    mode=pov_mode,
                )
                params = [pov_filename, render_filename, render_shape, "color"]
                with open(pov_filename, "w") as pf:
                    pf.write(pov)
                execute_pov(params)
            else:
                p_e("Could not find corresponding GPX")
                return False
        elif mode == 4:
            pov_mode = "gradient"
            gradient_render = os.path.isfile(render_filename)
            gradient_path, _ = create_color_gradient_image()
            if not gradient_render:
                pov = primary_pov(
                    dem_path, raster_data, texture_path=gradient_path, mode=pov_mode
                )
                params = [pov_filename, render_filename, render_shape, pov_mode]
                with open(pov_filename, "w") as pf:
                    pf.write(pov)
                execute_pov(params)
            locs = find_visible_coordinates_in_render(ds_name, gradient_path, dem_path)

            radius = 150  # in meters
            mountains_in_sight = find_visible_items_in_ds(
                dem_path, locs, mountains, radius=radius
            )
            plot_filename = f"src/templates/{panorama_filename}.html"
            plot_to_map(
                mountains_in_sight,
                coordinates,
                plot_filename,
                dem_path,
                locs=locs,
                mountains=mountains,
                mountain_radius=radius,
            )
        else:
            return False
    stats = [
        "Information about completed task: \n",
        "File:      %s" % panorama_filename,
        "Mode:      %s" % mode,
        "Duration:  %i seconds" % (time.time() - start_time),
    ]
    subprocess.call(["rm", "-r", "dev/cropped.png.aux.xml", "dev/cropped.png"])
    p_line(stats)
    return True


def render_height(IMAGE_DATA):
    start_time = time.time()

    panorama_path = IMAGE_DATA.path
    render_filename = IMAGE_DATA.render_path
    pov_filename = "/tmp/pov_file.pov"

    render_settings_path = "render_settings.json"
    with open(render_settings_path) as json_file:
        data = load(json_file)
        dem_path = data["dem_path"]
        render_width = data["render_width"]
        render_height = data["render_height"]

        render_shape = [render_width, render_height]
        json_file.close()

    dem_path, _, coordinates, _ = get_mountain_data(dem_path, panorama_path)

    raster_data = get_raster_data(dem_path, coordinates)
    if not raster_data:
        return

    pov_mode = "height"
    pov = primary_pov(dem_path, raster_data, mode=pov_mode)
    params = [pov_filename, render_filename, render_shape, "color"]
    with open(pov_filename, "w") as pf:
        pf.write(pov)
    pf.close()
    execute_pov(params)
    stats = [
        "Information about completed task: \n",
        f"File:      {IMAGE_DATA.filename}",
        f"Mode:      {pov_mode}",
        f"Duration:  {time.time() - start_time} seconds",
    ]
    p_line(stats)
    return True


def mountain_lookup(IMAGE_DATA, gpx_file, plot=False):
    p_i(f"Beginning mountain lookup for {IMAGE_DATA.filename}")
    pov_filename = "/tmp/pov_file.pov"

    im_desc = get_image_description(IMAGE_DATA.path)
    custom_tags = ast.literal_eval(im_desc)
    fov = custom_tags["fov"]
    imdims = custom_tags["imdims"]

    render_settings_path = "render_settings.json"
    with open(render_settings_path) as json_file:
        data = load(json_file)
        dem_path = data["dem_path"]
        scale_factor = 0.75
        if imdims:
            render_width = imdims[1] * scale_factor
            render_height = imdims[0] * scale_factor
        else:
            render_width = data["render_width"]
            render_height = data["render_height"]

        render_shape = [render_width, render_height]
        json_file.close()

    dem_path, original_dem, coordinates, viewing_direction = get_mountain_data(
        dem_path, IMAGE_DATA, True
    )

    raster_data = get_raster_data(dem_path, coordinates)
    if not raster_data:
        return

    locs_filename = f"{IMAGE_DATA.folder}/{IMAGE_DATA.filename}-locs.pkl"
    if not os.path.exists(locs_filename):

        pov_mode = "gradient"
        gradient_path, _ = create_color_gradient_image()
        if not os.path.exists(IMAGE_DATA.gradient_path):
            pov = primary_pov(
                dem_path,
                raster_data,
                texture_path=gradient_path,
                mode=pov_mode,
                fov=fov,
            )
            params = [pov_filename, IMAGE_DATA.gradient_path, render_shape, pov_mode]
            with open(pov_filename, "w") as pf:
                pf.write(pov)
            execute_pov(params)

        ds_name = original_dem.split("/")[-1].split(".")[0]
        locs = find_visible_coordinates_in_render(
            ds_name, gradient_path, IMAGE_DATA.gradient_path, dem_path
        )
        with open(locs_filename, "wb") as f:
            pickle.dump(locs, f)
    else:
        with open(locs_filename, "rb") as f:
            locs = pickle.load(f)

    ds_raster = raster_data[1][0]
    crs = int(ds_raster.crs.to_authority()[1])
    lat, lon = coordinates[0], coordinates[1]

    converter = LatLngToCrs(crs)
    camera_height = convert_coordinates(
        ds_raster, converter, lat, lon, only_height=True
    )
    camera_location = Location(lat, lon, camera_height)
    radius = 150  # in meters

    images = read_image_locations(
        IMAGE_DATA.filename, "src/static/images", ds_raster, converter
    )
    images_in_sight = find_visible_items_in_ds(locs, images, radius=radius)

    mountains_3d_path = f"{IMAGE_DATA.folder}/{IMAGE_DATA.filename}-{gpx_file.split('/')[-1].split('.')[0]}-3d.pkl"
    if not os.path.exists(mountains_3d_path):
        mountains = read_mountain_gpx(gpx_file, converter)
        mountains_in_sight = find_visible_items_in_ds(locs, mountains, radius=radius)
        mountains_3d = get_3d_location(
            camera_location,
            viewing_direction,
            converter,
            mountains_in_sight,
        )

        pickle.dump(mountains_3d, open(mountains_3d_path, "wb"))
    else:
        mountains = read_mountain_gpx(gpx_file, converter)
        mountains_3d = pickle.load(open(mountains_3d_path, "rb"))

    images_3d = get_3d_location(
        camera_location,
        viewing_direction,
        converter,
        images_in_sight,
    )

    converter_to_latlng = CrsToLatLng(crs)

    if plot:
        plot_filename = f"{IMAGE_DATA.folder}/{IMAGE_DATA.filename}-{gpx_file.split('/')[-1].split('.')[0]}.html"
        plot_to_map(
            mountains_3d,
            coordinates,
            plot_filename,
            dem_path,
            converter_to_latlng,
            mountain_radius=radius,
            locs=locs,
            mountains=mountains,
            images=images,
        )

    return mountains_3d, images_3d


def execute_pov(params):
    pov_filename, out_filename, dimensions, mode = params
    out_width, out_height = dimensions
    p_i("Generating %s" % out_filename)
    if mode == "color" or mode == "gradient":
        subprocess.call(
            [
                "povray",
                "+W%d" % out_width,
                "+H%d" % out_height,
                "Output_File_Type=N Bits_Per_Color=16 +Q8 +UR +A",
                "-GA",
                "+I" + pov_filename,
                "+O" + out_filename,
            ]
        )
    else:
        subprocess.call(
            [
                "povray",
                "+W%d" % out_width,
                "+H%d" % out_height,
                "Output_File_Type=N Bits_Per_Color=16 Display=off",
                "-GA",
                "Antialias=off Quality=0 File_Gamma=1.0",
                "+I" + pov_filename,
                "+O" + out_filename,
            ]
        )
