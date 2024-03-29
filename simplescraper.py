#!/usr/bin/env python3
import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import os
import logging
import zipfile
import traceback

l = logging.getLogger("SimpleScraper")
l.addHandler(logging.StreamHandler())
l.setLevel(logging.WARNING)


def get_retry(*args, session=None, max_retries=3, **kwargs):
    s = session if session is not None else requests.session()
    for retry_no in range(max_retries):
        try:
            r = s.get(*args, **kwargs)
        except Exception as err:
            l.warning('request failed %s', str(err.args))
            if retry_no == max_retries - 1:
                raise err

            # these exceptions prevent r from being created
            r = requests.Response
            r.status_code = 0

        if r.status_code == 200:
            break

    return r


def get_srcset_urls_from_tags(tags):
    """Get the srcset urls from a given iterable of Beautifulsoup tags"""
    sources_srcsets_raw = [source['srcset'] for source in tags if source.has_attr('srcset') is True]
    sources_srcsets = [[i.split(" ")[0] for i in raw_srcset.split(", ")] for raw_srcset in sources_srcsets_raw]
    sources_srcsets = sum(sources_srcsets, [])
    return sources_srcsets


def get_img_links(soup, response):
    """Returns an actual link to images and the original relative link from the page"""
    imgs = soup.find_all('img')
    img_srcs = [img['src'] for img in imgs if img.has_attr('src') is True]

    img_srcsets = get_srcset_urls_from_tags(imgs)
    all_src_links = img_srcs + img_srcsets
    links = [(urljoin(response.url, src), src) if not src.startswith('http') else (src, src) for src in all_src_links]
    l.debug('%d image links found', len(links))
    return list(set(links))


def get_source_links(soup, response):
    """Returns an actual link to source tags and the original relative link from the page"""
    sources = soup.find_all('source')
    sources_srcs = [source['src'] for source in sources if source.has_attr('src') is True]
    # also get srcsets
    sources_srcsets = get_srcset_urls_from_tags(sources)
    all_src_links = sources_srcs + sources_srcsets
    links = [(urljoin(response.url, src), src) if not src.startswith('http') else (src, src) for src in all_src_links]
    l.debug('%d image links found', len(links))
    return list(set(links))


def get_stylesheet_links(soup, response):
    """Returns an actual link to stylesheets and the original relative link from the page"""
    links = soup.find_all('link')
    link_srcs = [link['href'] for link in links if link.has_attr('rel') is True and link['rel'] == ['stylesheet']]
    links = [(urljoin(response.url, src), src) if not src.startswith('http') else (src, src) for src in link_srcs]
    l.debug('%d css links found', len(links))
    return list(set(links))


def get_js_links(soup, response):
    """Returns an actual link to js scripts and the original relative link from the page"""
    links = soup.find_all('script')
    link_srcs = [link['src'] for link in links if link.has_attr('src') is True]
    links = [(urljoin(response.url, src), src) if not src.startswith('http') else (src, src) for src in link_srcs]
    return list(set(links))


def get_usable_filename_from_url(url):
    """get a usable filename from a url. Pretty bad form but deals with sites like
    giphy that name all files the exact same thing"""
    cleaned_url = url[url.index(':') + 1:] if ':' in url else url
    cleaned_url = cleaned_url.strip('/').replace('/', '_')
    # clean js and css parameters?
    cleaned_url = re.sub(r'(?<=\.css)(\?[^/]+)$', '', cleaned_url)
    cleaned_url = re.sub(r'(?<=\.js)(\?[^/]+)$', '', cleaned_url)
    cleaned_url = cleaned_url
    return cleaned_url


def download_media(url, destination, session=None):
    """url: url to download from
    destination: file path to save to"""
    s = session if session is not None else requests.session()
    r = s.get(url, stream=True)
    with open(destination, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)


def zip_files(new_files, destination_dir):
    zipfile_name = 'site' if os.getcwd() == destination_dir else os.path.split(destination_dir)[-1]
    zipfile_name += '.zip'
    l.info('Zipping files into %s', zipfile_name)
    try:
        with zipfile.ZipFile(zipfile_name, 'w') as z:
            for filename in new_files:
                z.write(filename)
    except:
        l.warning('Error with zipfile %s', zipfile_name)
        traceback.print_exc()


def copy_page(url, destination_dir, args):
    s = requests.session()
    r = s.get(url)
    if r.status_code != 200:
        logging.warning('url %s responded with non 200 status code: %d', url, r.status_code)
        return
    base_page_filename = 'index.html'
    # this is just for the zipfile
    destdir_name = '.' if os.getcwd() == destination_dir else os.path.split(destination_dir)[-1]
    base_page_path = os.path.join(destination_dir, base_page_filename)
    # write to disk first in case downloading images goes poorly
    with open(base_page_path, 'wb') as f:
        f.write(r.content)
    l.info('%s Downloaded and saved', base_page_filename)

    l.info('Beginning to download additional resources')
    soup = BeautifulSoup(r.content, 'html.parser')
    img_links = get_img_links(soup, r)
    stylesheet_links = get_stylesheet_links(soup, r)
    source_links = get_source_links(soup, r)
    js_links = get_js_links(soup, r) if args.ignore_js is False else []

    all_additional_links = img_links + stylesheet_links + js_links + source_links
    if args.ignore is not None:
        try:
            ignore_regex = re.compile(args.ignore)
            l.debug('%s', str(ignore_regex))
            all_additional_links = [(link, rel_link) for link, rel_link in all_additional_links
                                    if re.search(ignore_regex, rel_link) is None]
        except:
            l.warning('regex failed to compile, nothing will be ignored')

    updated_page = r.content
    created_files_relative_path = []
    for link, rel_link in all_additional_links:
        new_filename = get_usable_filename_from_url(link)
        dest = os.path.join(destination_dir, new_filename)
        try:
            l.info('Downloading %s', link)
            download_media(link, dest, session=s)
        except Exception as err:
            l.debug('Issue downloading %s', err.args)
            l.warning('Issue downloading %s. This file will be skipped', link)
            continue

        replacement_path = os.path.join('.', new_filename)
        created_files_relative_path.append(os.path.join(destdir_name, new_filename))

        updated_page = re.sub(re.escape(rel_link.encode()), replacement_path.encode(), updated_page)

    if args.zip is True:
        zip_files(created_files_relative_path, destination_dir)

    l.info('Updating %s', base_page_path)
    with open(base_page_path, 'wb') as f:
        f.write(updated_page)
    l.info('%s updated', base_page_path)


def main(urls, destination_dir, args):

    destination_dir = os.path.abspath(destination_dir)
    # setup destination
    if not os.path.isdir(destination_dir):
        os.mkdir(destination_dir)

    for url in urls:
        copy_page(url, destination_dir, args)


if __name__ == '__main__':
    import argparse
    description = """A basic scraper to make archived copies of websites.
    This scraper only downloads html, media files, javascript files, and css"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('-j', '--ignore-js', action='store_true', default=False,
                        help='Do not download js files')
    parser.add_argument('-d', '--destination', default=os.getcwd(),
                        help='Destination directory. Defaults to current directory')
    parser.add_argument('-z', '--zip', action='store_true', default=False,
                        help='Automatically create a zip file containing all of the files from the site')
    parser.add_argument('-i', '--ignore',
                        help='Regex for filenames to ignore')
    parser.add_argument("-iss", "--ignore-full-sourcesets", default=False,
                        action="store_true",
                        help="Don't fetch all versions of image/audio sources. "
                             "Stick with the default sizes. Not yet implemented")
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Enable debug functionality, not fully implemented')
    parser.add_argument('urls', nargs=argparse.REMAINDER, default=[],
                        help='Urls to scrape')
    args = parser.parse_args()
    if args.debug is True:
        l.setLevel(logging.DEBUG)
    l.debug('%s', args)
    main(args.urls, args.destination, args)
