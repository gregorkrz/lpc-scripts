#!/usr/bin/env python3

"""Returns a list of files from a dataset including only files that are hosted on disk."""

import os,sys,getpass,warnings,glob,shlex,subprocess,argparse # pylint: disable=multiple-imports
from collections import defaultdict
import pickle
from urllib.parse import urlparse

from subprocess import STDOUT, check_output


def getOS():
    """Gets OS version from shell (other methods return host OS when in container)"""
    cmd = r"sed -nr 's/[^0-9]*([0-9]+).*/\1/p' /etc/redhat-release"
    osv = subprocess.check_output(shlex.split(cmd), encoding="utf-8").rstrip()
    return osv

def file_is_available(rep):
    print("Checking if file", rep["name"], "is available on disk")
    filepath = rep["name"]
    urls = list(rep["pfns"].keys())
    print("urls", urls)
    host = urlparse(urls[0]).netloc
    cmd = f"xrdfs {host} stat {filepath}"
    #print(cmd)
    #output = check_output(cmd, stderr=STDOUT, timeout=1.0)
    #print(output)
    try:
        output =subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1.0)
        print(output)
    except subprocess.TimeoutExpired:
        print("Timeout")
        return False
    except subprocess.CalledProcessError as e:
        print("Error", e)
        return False
    return True

def getHosted(dataset, user, allow=None, block=None):
    """Gets list of files on disk for a dataset, and list of sites along with how many files each site has"""
    if allow is not None and block is not None:
        raise RuntimeError("Cannot specify both allow list and block list, pick one")

    osv = getOS()
    rucio_path = f'/cvmfs/cms.cern.ch/rucio/x86_64/rhel{osv}/py3/current'
    os.environ['RUCIO_HOME'] = rucio_path
    os.environ['RUCIO_ACCOUNT'] = user
    full_rucio_path = glob.glob(rucio_path+'/lib/python*.*')[0]
    sys.path.insert(0,full_rucio_path+'/site-packages/')

    warnings.filterwarnings("ignore", message=".*cryptography.*")
    from rucio.client.client import Client # pylint: disable=import-error,import-outside-toplevel
    client = Client()

    # loop over blocks to avoid timeout error from too-large response
    all_blocks = list(client.list_content(scope='cms',name=dataset))
    # batch some blocks together for fewer requests
    # not fully optimized, but n=10 tested to be ~15% faster than n=1
    nblocks = 10
    block_groups = [all_blocks[i:i+nblocks] for i in range(0, len(all_blocks), nblocks)]

    from rucio.client.replicaclient import ReplicaClient # pylint: disable=import-error,import-outside-toplevel
    rep_client = ReplicaClient()

    filelist = set()
    sitelist = defaultdict(int)
    def sitecond(site):
        return ("_Tape" not in site) and (allow is None or site in allow) and (block is None or site not in block)
    for block_group in block_groups:
        reps = list(rep_client.list_replicas([{'scope': 'cms', 'name': block['name']} for block in block_group]))
        for rep in reps:
            for site,state in rep['states'].items():
                #if rep["name"] == "/store/mc/RunIISummer20ULPrePremix/Neutrino_E-10_gun/PREMIX/UL18_106X_upgrade2018_realistic_v11_L1v1-v2/00005/43187DF0-9E2B-8A43-A493-2CD77528929A.root":
                #if rep["name"] == "/store/mc/RunIISummer20ULPrePremix/Neutrino_E-10_gun/PREMIX/UL18_106X_upgrade2018_realistic_v11_L1v1-v2/230006/886356A0-2BF3-E045-8F22-B4E204CF50AB.root":
                #    print(rep)
                #    print("------")
                if state=='AVAILABLE' and sitecond(site):
                    #if file_is_available(rep):
                    filelist.add(rep['name'])
                    sitelist[site] += 1
    print("Found", len(filelist), "available files on disk")
    sys.path.pop(0)
    return filelist, sitelist

def main(dataset, user, outfile=None, verbose=False, allow=None, block=None):
    """Prints file list and site list"""
    filelist, sitelist = getHosted(dataset, user, allow=allow, block=block)

    #if verbose:
    #    print("Site list:")
    #    print("\n".join(f'{k}: {v}' for k,v in sitelist.items()))
    import unicodedata
    #file = open(outfile,'w') if outfile is not None else sys.stdout # pylint: disable=consider-using-with,unspecified-encoding
    #if outfile is not None: file.close() # pylint: disable=multiple-statements
    if outfile is not None:
        # pickle
        #pickle.dump(filelist, open(outfile, "wb"))
        # dump using protocol 2
        with open(outfile, "wb") as f:
            pickle.dump([x.encode('utf-8') for x in list(filelist)], f, protocol=2)
        print("Saved into file", outfile)
    else: print("\n".join(filelist))


if __name__=="__main__":
    default_user = getpass.getuser()
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Find all available files (those hosted on disk) for a given dataset"
    )
    site_args = parser.add_mutually_exclusive_group(required=False)
    site_args.add_argument("-a","--allow",type=str,default=None,nargs='*',help="allow only these sites")
    site_args.add_argument("-b","--block",type=str,default=None,nargs='*',help="block these sites")
    parser.add_argument("-o","--outfile",type=str,default=None,help="write to this file instead of stdout")
    parser.add_argument("-u","--user",type=str,default=default_user,help="username for rucio")
    parser.add_argument("-v","--verbose",default=False,action="store_true",help="print extra information (site list)")
    parser.add_argument("dataset",type=str,help="dataset to query")
    args = parser.parse_args()

    main(args.dataset, args.user, outfile=args.outfile, verbose=args.verbose, allow=args.allow, block=args.block)
