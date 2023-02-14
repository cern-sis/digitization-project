from glob import glob
import click
import logging
import os
import pysftp
import re
import shutil
import sys
import xml.etree.ElementTree as ET


URL = "https://digitization.web.cern.ch"

main_directory = (
    "/eos/project/p/psdigitization/public/CERN-Project-Files/CERN-Project-Files/www"
)
ERROR = []
MISSING_XMLS = []
REGEXP = r"(?!original)([\w\W]+)\.(xml)"
MAX_NUMBER_OF_RECORDS_COLLECT = 500


def url_from_eos_path(path):
    return path.replace(main_directory, URL)


def records_collection(input_dir, output_dir):
    records_collection_dict, dict_key = {}, 0
    records_collection = []
    logging.info("Finding XML files")
    for dir in os.walk(input_dir):
        for file_path in glob(os.path.join(dir[0], "*.xml")):
            file_name = file_path.split("/")[-1]
            if re.match(REGEXP, file_name):
                if len(records_collection) == MAX_NUMBER_OF_RECORDS_COLLECT:
                    dict_key += 1
                    records_collection_dict[dict_key] = records_collection
                    records_collection.clear()
                    logging.info("{} collection created.".format(dict_key))
                else:
                    records_collection.append(file_path)
    records_collection_dict[dict_key + 1] = records_collection
    logging.info("Searching completed.")

    for k, records_collection in records_collection_dict.items():
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        filename = "{}/{}.xml".format(output_dir, k)

        with open(filename, "w") as nf:
            nf.write("<collection>")
            for record_path in records_collection:
                with open(record_path, "r") as f:
                    logging.info("Reading {}".format(record_path))
                    data = f.read()

                # Remove collection tag to have only one per xml file
                data = data.replace("<collection>", "")
                data = data.replace("</collection>", "")

                # Write the xml in the collection
                logging.info("Writing in the collection {}".format(filename))
                nf.write(data)

            nf.write("</collection>")

        logging.info("Collection {} written successfully.".format(k))


def fix_white_spaces_in_directory(start_dir):
    for root, dirs, files in os.walk(start_dir, topdown=False):
        for directory in dirs:
            if " " in directory:
                new_directory = directory.replace(" ", "_")
                os.rename(
                    os.path.join(root, directory), os.path.join(root, new_directory)
                )
                print(f"Renamed directory: {directory} -> {new_directory}")
        for filename in files:
            if " " in filename:
                new_filename = filename.replace(" ", "_")
                os.rename(
                    os.path.join(root, filename), os.path.join(root, new_filename)
                )
                print(f"Renamed file: {filename} -> {new_filename}")


def download_files_from_ftp(force=False):
    host = os.getenv("FTP_HOST")
    username = os.getenv("FTP_USERNAME")
    password = os.getenv("FTP_PASSWORD")

    main_directory = os.getenv("FTP_ROOT_PATH", "/CERN-Project-Files")
    download_directory = os.getenv("DOWNLOAD_DIR", "/tmp/")

    cnopts = pysftp.CnOpts()
    cnopts.hostkeys = None
    downloaded_directories = []
    with pysftp.Connection(
        host=host, username=username, password=password, cnopts=cnopts
    ) as sftp:
        sftp.cwd(main_directory)
        directory_structure = sftp.listdir_attr()
        for attr in directory_structure:
            if force or not os.path.isdir(
                os.path.join(download_directory, attr.filename)
            ):
                click.echo(f"Downloading `{attr.filename}`.")
                remoteFilePath = attr.filename
                localFilePath = download_directory
                sftp.get_r(remoteFilePath, localFilePath, preserve_mtime=True)
                downloaded_directories.append(attr.filename)
            else:
                click.echo(
                    f"Directory already exists`{attr.filename}`. Skip downloading..."
                )
    return downloaded_directories


def fix_xml(root, xml_path, tif_path, pdf_path):
    xml_file_name = os.path.basename(xml_path)
    xml_file_name_original = "original_{}".format(xml_file_name)
    xml_path_original = os.path.join(root, xml_file_name_original)

    if os.path.isfile(xml_path):
        if os.path.isfile(xml_path_original):
            click.echo("We have original")
            os.remove(xml_path)
            shutil.copy2(
                os.path.join(root, "original_{}".format(xml_file_name)), xml_path
            )
        else:
            click.echo("Saving the original file")
            shutil.copy2(
                xml_path, os.path.join(root, "original_{}".format(xml_file_name))
            )
    else:
        click.echo("XML files are missing completely!")
        MISSING_XMLS.append(xml_path)

    pdf_url = url_from_eos_path(pdf_path)
    tif_url = url_from_eos_path(tif_path)

    try:
        tree = ET.parse(xml_path)
        xml_root = tree.getroot()
        for x in xml_root.findall('.//datafield[@tag="FFT"]'):
            if x.find('.//subfield[@code="a"]').text.startswith("[PATH]"):
                x.find('.//subfield[@code="a"]').text = pdf_url

            elif x.find('.//subfield[@code="a"]').text.startswith("[EOS_PATH]"):
                x.attrib["tag"] = "856"
                x.attrib["ind1"] = "4"
                for child in x.getchildren():
                    if child.attrib["code"] == "d":
                        x.remove(child)
                    if child.attrib["code"] == "a":
                        child.attrib["code"] = "u"
                        child.text = tif_url
                    if child.attrib["code"] == "t":
                        child.attrib["code"] = "q"
                        child.text = "TIFF"
        tree.write(xml_path, encoding="utf-8")
    except Exception:
        ERROR.append(xml_path)


def find_all_xmls():
    os.chdir(main_directory)
    for root, dirs, files in os.walk(main_directory, topdown=False):
        try:
            xml_path = os.path.join(
                root,
                next(
                    filter(
                        lambda x: not x.startswith("original_") and x.endswith(".xml"),
                        files,
                    )
                ),
            )
            tif_path = os.path.join(
                root, next(filter(lambda x: x.endswith(".tif"), files))
            )
            pdf_path = os.path.join(
                root, next(filter(lambda x: x.endswith(".pdf"), files))
            )
        except StopIteration:
            continue
        fix_xml(root, xml_path, tif_path, pdf_path)
        click.echo(xml_path)

        test_file = os.path.join(root, "test.xml")
        if os.path.isfile(test_file):
            os.remove(test_file)
            click.echo(test_file)


@click.group()
def digitization():
    pass


@digitization.command()
@click.option("--force", default=False, show_default=True, is_flag=True)
@click.option("--fix-eos-paths", default=False, show_default=True, is_flag=True)
@click.option("--fix-white-spaces", default=False, show_default=True, is_flag=True)
@click.option(
    "--create-collection-file", default=False, show_default=True, is_flag=True
)
def download(force, fix_eos_paths, fix_white_spaces, create_collection_file):
    """Download files from ftp."""

    click.echo("Downloading new files.")
    downloaded_directories = download_files_from_ftp(force=force)
    download_directory = os.getenv("DOWNLOAD_DIR", "/tmp/")

    if fix_white_spaces:
        click.echo("Fixing white spaces in directories and files.")
        for directory in downloaded_directories:
            fix_white_spaces_in_directory(os.path.join(download_directory, directory))

    if fix_eos_paths:
        click.echo("Fixing paths in xml.")
        find_all_xmls()

    if create_collection_file:
        click.echo("Creating collection file.")
        for directory in downloaded_directories:
            records_collection(
                os.path.join(download_directory, directory),
                os.path.join(download_directory, directory),
            )


@digitization.command("fix-eos-paths")
def fix_eos_paths():
    """Fix EOS paths."""
    click.echo("Fixing paths in xml")
    find_all_xmls()


@digitization.command("fix-white-spaces")
@click.option("-d", "--start-from-dir", type=str)
def fix_white_spaces(start_from_dir):
    """Fix white spaces."""
    click.echo(f"Fixing white spaces in directories and files. {start_from_dir}")
    fix_white_spaces_in_directory(start_from_dir)


@digitization.command("create-collection-file")
@click.option("-d", "--start-from-dir", type=str)
@click.option("-o", "--output-dir", type=str)
def fix_white_spaces(start_from_dir, output_dir):
    """Fix white spaces."""
    click.echo(
        f"Fixing white spaces in directories and files. {start_from_dir} and {output_dir}"
    )
    fix_white_spaces_in_directory(start_from_dir)
    records_collection(start_from_dir, output_dir)


if __name__ == "__main__":
    digitization()
