#!/usr/bin/env python
import os
import sys
import subprocess
import string
import fnmatch
import shutil
import optparse
from common import *
from time import sleep


def test_repositories(ros_distro, repo_list, version_list, workspace, test_depends_on):
    print "Testing on distro %s"%ros_distro
    print "Testing repositories %s"%', '.join(repo_list)
    print "Testing versions %s"%', '.join(version_list)
    if test_depends_on:
        print "Testing depends-on"
    else:
        print "Not testing depends on"

    # set directories
    tmpdir = os.path.join('/tmp', 'test_repositories')
    repo_sourcespace = os.path.join(tmpdir, 'src_repository')
    dependson_sourcespace = os.path.join(tmpdir, 'src_depends_on')
    repo_buildspace = os.path.join(tmpdir, 'build_repository')
    dependson_buildspace = os.path.join(tmpdir, 'build_depend_on')

    # Add ros sources to apt
    print "Add ros sources to apt"
    with open('/etc/apt/sources.list.d/ros-latest.list', 'w') as f:
        f.write("deb http://packages.ros.org/ros-shadow-fixed/ubuntu %s main"%os.environ['OS_PLATFORM'])
    call("wget http://packages.ros.org/ros.key -O %s/ros.key"%workspace)
    call("apt-key add %s/ros.key"%workspace)
    call("apt-get update")

    # install stuff we need
    print "Installing Debian packages we need for running this script"
    call("apt-get install python-catkin-pkg python-rosinstall --yes")

    # parse the rosdistro file
    print "Parsing rosdistro file for %s"%ros_distro
    distro = RosDistro(ros_distro, prefetch_dependencies=test_depends_on, prefetch_upstream=False)
    print "Parsing devel file for %s"%ros_distro
    devel = DevelDistro(ros_distro)

    # Create rosdep object
    print "Create rosdep object"
    rosdep = RosDepResolver(ros_distro)

    # download the repo_list from source
    print "Creating rosinstall file for repo list"
    rosinstall = ""
    for repo, version in zip(repo_list, version_list):
        if version == 'devel':
            if not devel.repositories.has_key(repo):
                raise BuildException("Repository %s does not exist in Devel Distro"%repo)
            print "Using devel distro file to download repositories"
            rosinstall += devel.repositories[repo].get_rosinstall()
        else:
            if not distro.repositories.has_key(repo):
                raise BuildException("Repository %s does not exist in Ros Distro"%repo)
            if version == 'latest':
                print "Using latest release distro file to download repositories"
                rosinstall += distro.repositories[repo].get_rosinstall_latest()
            else:
                print "Using version %s of release distro file to download repositories"%version
                rosinstall += distro.repositories[repo].get_rosinstall_release(version)
    print "rosinstall file for all repositories: \n %s"%rosinstall
    with open(os.path.join(workspace, "repo.rosinstall"), 'w') as f:
        f.write(rosinstall)
    print "Install repo list from source"
    os.makedirs(repo_sourcespace)
    call("rosinstall %s %s/repo.rosinstall --catkin"%(repo_sourcespace, workspace))

    # get the repositories build dependencies
    print "Get build dependencies of repo list"
    repo_build_dependencies = get_dependencies(repo_sourcespace, build_depends=True, test_depends=False)
    print "Install build dependencies of repo list: %s"%(', '.join(repo_build_dependencies))
    apt_get_install(repo_build_dependencies, rosdep)

    # replace the CMakeLists.txt file for repositories that use catkin
    print "Removing the CMakeLists.txt file generated by rosinstall"
    os.remove(os.path.join(repo_sourcespace, 'CMakeLists.txt'))
    print "Create a new CMakeLists.txt file using catkin"
    ros_env = get_ros_env('/opt/ros/%s/setup.bash'%ros_distro)
    call("catkin_init_workspace %s"%repo_sourcespace, ros_env)
    os.makedirs(repo_buildspace)
    os.chdir(repo_buildspace)
    call("cmake %s"%repo_sourcespace, ros_env)
    ros_env_repo = get_ros_env(os.path.join(repo_buildspace, 'devel/setup.bash'))

    # build repositories
    print "Build repo list"
    print "CMAKE_PREFIX_PATH: %s"%ros_env['CMAKE_PREFIX_PATH']
    call("make", ros_env)

    # get the repositories test dependencies
    print "Get test dependencies of repo list"
    repo_test_dependencies = get_dependencies(repo_sourcespace, build_depends=False, test_depends=True)
    print "Install test dependencies of repo list: %s"%(', '.join(repo_test_dependencies))
    apt_get_install(repo_test_dependencies, rosdep)

    # run tests
    print "Test repo list"
    print "CMAKE_PREFIX_PATH: %s"%ros_env['CMAKE_PREFIX_PATH']
    call("make run_tests", ros_env)

    # see if we need to do more work or not
    if not test_depends_on:
        print "We're not testing the depends-on repositories"
        copy_test_results(workspace, repo_buildspace)
        return

    # get repo_list depends-on list
    print "Get list of wet repositories that build-depend on repo list %s"%', '.join(repo_list)
    depends_on = []
    for d in distro.depends_on(repo_list, 'build'):
        if not d in depends_on and not d in repo_list:
            depends_on.append(d)
    print "Build depends_on list of repo list: %s"%(', '.join(depends_on))
    if len(depends_on) == 0:
        copy_test_results(workspace, repo_buildspace)
        print "No wet groovy repositories depend on our repo list. Test finished here"
        return

    # install depends_on repositories from source
    rosinstall = ""
    for d in depends_on:
        rosinstall += distro.packages[d].get_rosinstall_release()
    print "Rosinstall for depends_on:\n %s"%rosinstall
    with open(workspace+"/depends_on.rosinstall", 'w') as f:
        f.write(rosinstall)
    print "Created rosinstall file for depends on"

    # install all repository and system dependencies of the depends_on list
    print "Install all depends_on from source"
    os.makedirs(dependson_sourcespace)
    call("rosinstall --catkin %s %s/depends_on.rosinstall"%(dependson_sourcespace, workspace))

    # get build and test dependencies of depends_on list
    dependson_build_dependencies = []
    for d in get_dependencies(dependson_sourcespace, build_depends=True, test_depends=False):
        if not d in dependson_build_dependencies and not d in depends_on and not d in repo_list:
            dependson_build_dependencies.append(d)
    print "Build dependencies of depends_on list are %s"%(', '.join(dependson_build_dependencies))
    dependson_test_dependencies = []
    for d in get_dependencies(dependson_sourcespace, build_depends=False, test_depends=True):
        if not d in dependson_test_dependencies and not d in depends_on and not d in repo_list:
            dependson_test_dependencies.append(d)
    print "Test dependencies of depends_on list are %s"%(', '.join(dependson_test_dependencies))


    # install build dependencies
    print "Install all build dependencies of the depends_on list"
    apt_get_install(dependson_build_dependencies, rosdep)

    # replace the CMakeLists.txt file again
    print "Removing the CMakeLists.txt file generated by rosinstall"
    os.remove(os.path.join(dependson_sourcespace, 'CMakeLists.txt'))
    os.makedirs(dependson_buildspace)
    os.chdir(dependson_buildspace)
    print "Create a new CMakeLists.txt file using catkin"
    call("catkin_init_workspace %s"%dependson_sourcespace, ros_env)
    call("cmake %s"%dependson_sourcespace, ros_env)
    ros_env_depends_on = get_ros_env(os.path.join(dependson_buildspace, 'devel/setup.bash'))

    # build repositories
    print "Build depends-on repositories"
    call("make", ros_env)

    # install test dependencies
    print "Install all test dependencies of the depends_on list"
    apt_get_install(dependson_test_dependencies, rosdep)

    # test repositories
    print "Test depends-on repositories"
    call("make run_tests", ros_env)
    copy_test_results(workspace, dependson_buildspace)




def main():
    parser = optparse.OptionParser()
    parser.add_option("--depends_on", action="store_true", default=False)
    (options, args) = parser.parse_args()

    if len(args) <= 2 or len(args)%2 != 1:
        print "Usage: %s ros_distro repo1 version1 repo2 version2 ..."%sys.argv[0]
        print " - with ros_distro the name of the ros distribution (e.g. 'fuerte' or 'groovy')"
        print " - with repo the name of the repository"
        print " - with version 'latest', 'devel', or the actual version number (e.g. 0.2.5)."
        raise BuildException("Wrong arguments for test_repositories script")

    ros_distro = args[0]

    repo_list = [args[i] for i in range(1, len(args), 2)]
    version_list = [args[i+1] for i in range(1, len(args), 2)]
    workspace = os.environ['WORKSPACE']

    print "Running test_repositories test on distro %s and repositories %s"%(ros_distro,
                                                                      ', '.join(["%s (%s)"%(r,v) for r, v in zip(repo_list, version_list)]))
    test_repositories(ros_distro, repo_list, version_list, workspace, test_depends_on=options.depends_on)



if __name__ == '__main__':
    # global try
    try:
        main()
        print "test_repositories script finished cleanly"

    # global catch
    except BuildException as ex:
        print ex.msg

    except Exception as ex:
        print "test_repositories script failed. Check out the console output above for details."
        raise ex
