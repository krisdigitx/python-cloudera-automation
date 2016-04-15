#!/usr/bin/env python
import sys
import datetime
from cm_api.api_client import ApiResource
from cm_api.endpoints.cms import ClouderaManager
from cm_api.endpoints.clusters import ApiCluster
from cm_api.endpoints.services import ApiServiceSetupInfo
import socket
import time
import subprocess
from configobj import ConfigObj
import getopt
import os.path
import os
import paramiko
import select

def wait_command(stdout,server):
    while not stdout.channel.exit_status_ready():
        # Only print data if there is data to read in the channel
        if stdout.channel.recv_ready():
            rl, wl, xl = select.select([stdout.channel], [], [], 0.0)
            if len(rl) > 0:
                # Print data from stdout
                print server+">>",
                print stdout.channel.recv(1024)



def cdhproc(cluster_name,api,hostnames,server_rack,server_login,server_passwd,server_key,server_passphrase,cloudera_manager_repo):
    print "Creating cluster, ", cluster_name
    cluster = api.create_cluster(cluster_name, "CDH5")

    server_private_key = server_key
    hosts = [ ]                             # API host handles
    #hostnames.append("cdhmgr51.srv.ac.net.uk")
    #create hosts
    for name in hostnames:
	print "Creating host %s in cluster..." % (name)
        host = api.create_host(
          name,                             # Host id
          name,                             # Host name (FQDN)
          socket.gethostbyname(name),       # IP address
          server_rack)                  # Rack
        hosts.append(host)

    #add hosts to cluster
    print "Adding hosts to cluster"
    hi = ApiCluster(api, name=cluster_name)
    hi.add_hosts(hostnames)
    #for i in hosts:
    #    print "HOST"
        #hi.add_hosts(i.hostId)

    #Deploy SCM
    cms = ClouderaManager(api)
    #hostnames.append("cdhmgr51.srv.ac.net.uk")
    print "Deploying cloudera scm and components on all nodes...please wait for this to finish"
    #chi = cms.host_install("root", hostnames, ssh_port=22, password="jacobjesus",private_key=None, passphrase=None, parallel_install_count=None,cm_repo_url='http://192.168.0.30/cdh5/cdh5/cloudera-manager/', gpg_key_custom_url='http://192.168.0.30/cdh5/cdh5/cloudera-manager/RPM-GPG-KEY-cloudera')


    if server_key=="None":
        chi = cms.host_install(server_login, hostnames, ssh_port=22, password=server_passwd,private_key=None, passphrase=server_passphrase, parallel_install_count=None,cm_repo_url=cloudera_manager_repo, gpg_key_custom_url=None)
        cmd = chi.wait()
        print "Active: %s. Success: %s" % (cmd.active, cmd.success)
        if cmd.success == "False":
            print "SCM deployment failed"
            sys.exit(1)

    else:
        proc = open(server_key,"r")
        server_key = proc.read()
        proc.close()
        chi = cms.host_install(server_login, hostnames, ssh_port=22, password=None,private_key=server_key, passphrase=server_passphrase, parallel_install_count=None,cm_repo_url=cloudera_manager_repo, gpg_key_custom_url=None)
        cmd = chi.wait()
        print "Active: %s. Success: %s" % (cmd.active, cmd.success)
        if cmd.success == "False":
            print "SCM deployment failed"
            sys.exit(1)



def deployHDFSMAP(cluster_name,api,configfile):

    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    cluster_name = config['cluster']['name']
    server_login = config['cluster']['server_login']
    server_passwd = config['cluster']['server_passwd']
    server_key = config['cluster']['server_key']
    server_passphrase = config['cluster']['server_passphrase']
    hdfs_service = config['hdfs']['service_name']
    name_node_service_name = config['hdfs']['name_node_service_name']
    sec_name_node_service_name = config['hdfs']['sec_name_node_service_name']
    hdfs_datanodes = config['hdfs']['data_nodes']
    hdfs_namenode = config['hdfs']['name_node']
    hdfs_secnamenode = config['hdfs']['sec_name_node']
    cloudera_parcel_repo = config['cluster']['cloudera_parcel_repo']

    mr_service = config['mapreduce']['service_name']
    mr_jtnode = config['mapreduce']['jt_node']
    mr_ttnodes = config['mapreduce']['tt_nodes']
    mr_jtrolename = config['mapreduce']['jt_rolename']
    mr_ttrolename = config['mapreduce']['tt_rolename']


    print "Creating HDFS service"
    hdfs = cluster.create_service(hdfs_service, "HDFS")
    nn = hdfs.create_role(name_node_service_name, "NAMENODE", hdfs_namenode)
    snn = hdfs.create_role(sec_name_node_service_name, "SECONDARYNAMENODE", hdfs_secnamenode)
    j = 0
    for i in hdfs_datanodes:
        print "adding datanode"
        hdfs.create_role("hdfs01-dn" + str(j), "DATANODE", i)
        j += 1

    #configure HDFS
    hdfs_service_config = {
        'dfs_replication': 3,
        'dfs_permissions': 'false',
        'dfs_block_local_path_access_user': 'impala,hbase,mapred,spark'
    }
    nn_config = {
        'dfs_name_dir_list': '/dfs/nn',
        'dfs_namenode_handler_count': 30,
    }
    snn_config = {
        'fs_checkpoint_dir_list': '/dfs/snn',
    }
    dn_config = {
        'dfs_data_dir_list': '/dfs/dn1,/dfs/dn2,/dfs/dn3',
        'dfs_datanode_failed_volumes_tolerated': 1,
    }
    hdfs.update_config(hdfs_service_config)

    # Use a different set of data directories for DN3
    #hdfs.get_role('hdfs01-dn2').update_config({
    #    'dfs_data_dir_list': '/dn/data1,/dn/data2' })

    #for name, config in hdfs.get_config(view='full')[0].items():
    #    print "%s - %s - %s" % (name, config.relatedName, config.description)
    #get all all hdfs roles

    dn_groups = []
    for group in hdfs.get_all_role_config_groups():
        #print group.roleType
        if group.roleType == 'NAMENODE':
            dn_groups.append(group)
            group.update_config({
                'dfs_name_dir_list': '/dfs/nn',
                'dfs_namenode_handler_count': 30,
            })
        if group.roleType == 'DATANODE':
            dn_groups.append(group)
            group.update_config({
                'dfs_data_dir_list': '/dfs/dn1,/dfs/dn2,/dfs/dn3',
                'dfs_datanode_failed_volumes_tolerated': 1,
            })
        if group.roleType == 'SECONDARYNAMENODE':
            dn_groups.append(group)
            group.update_config({
                'fs_checkpoint_dir_list': '/dfs/snn',
            })
    #print dn_groups[0]




    #configure mapreduce
    print "Creating Mapreduce service"
    mr = cluster.create_service(mr_service, "MAPREDUCE")
    jt = mr.create_role(mr_jtrolename, "JOBTRACKER", mr_jtnode)
    j = 0
    for node in mr_ttnodes:
        mr.create_role(mr_ttrolename + str(j), "TASKTRACKER", node)
        j += 1


    mr_service_config = {
        'hdfs_service': hdfs_service,
    }
    jt_config = {
        'jobtracker_mapred_local_dir_list': '/mapred/jt',
        'mapred_job_tracker_handler_count': 40,
    }
    tt_config = {
        'tasktracker_mapred_local_dir_list': '/mapred/local',
        'mapred_tasktracker_map_tasks_maximum': 10,
        'mapred_tasktracker_reduce_tasks_maximum': 6,
    }

    gateway_config  = {
        'mapred_reduce_tasks': 10,
        'mapred_submit_replication': 2,
    }


    #print "MR"
    #print mr
    #for name, config in mr.get_config(view='full')[0].items():
    #    print "%s - %s - %s" % (name, config.relatedName, config.description)
    #mr.update_config(
    #    svc_config=mr_service_config )
    mr.update_config(
        {
        'hdfs_service': hdfs_service,
        })

    #get all all mapreduce roles
    mr_groups = []
    print "Updating mapreduce roles..."
    for group in mr.get_all_role_config_groups():
        #print group.roleType
        if group.roleType == 'TASKTRACKER':
            print "Updating tasktracker configs..."
            group.update_config({
                'tasktracker_mapred_local_dir_list': '/mapred/local',
                'mapred_tasktracker_map_tasks_maximum': 10,
                'mapred_tasktracker_reduce_tasks_maximum': 6,
            })
        if group.roleType == 'JOBTRACKER':
            print "updating jobtracker configs..."
            group.update_config({
                    'jobtracker_mapred_local_dir_list': '/mapred/jt',
                    'mapred_job_tracker_handler_count': 40,
                    'mapred_acls_enabled': 'true',
            })
        if group.roleType == 'GATEWAY':
            print "updating gateway configs..."
            group.update_config({
                    'mapred_reduce_tasks': 10,
                    'mapred_submit_replication': 2,
            })
    #print mr_groups[0]


    #Download and distribute parcel
    attempts = 0
    while attempts < 3:
        try:
            parcelMain(cluster_name,api,cloudera_parcel_repo)
            break
        except:
            print "parcel process failed, retrying again..."
            attempts += 1

    print "Stopping hdfs service..."
    cmd = hdfs.stop().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Stopping mapreduce service..."
    cmd = mr.stop().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    time.sleep(30)
    print "Formatting HDFS namenode"
    attempts = 0
    while attempts < 3:
        try:
            #CMD_TIMEOUT = 180 # format_hdfs takes a list of NameNodes
            cmd = hdfs.format_hdfs(name_node_service_name)[0]
            cmd.wait()
            print "Active: %s. Success: %s" % (cmd.active, cmd.success)
            break
        except:
            print "formatting HDFS namenode failed, trying again...."
            attempts += 1
            #if not cmd.wait(CMD_TIMEOUT).success:
            #    raise Exception("Failed to format HDFS")

    #restart HDFS service
    print "Restarting HDFS service..."
    cmd = hdfs.restart().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    #create mapred directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if server_key == "None":
        ssh.connect(hdfs_datanodes[0],username=server_login,password=server_passwd)
    else:
        ssh.connect(hdfs_datanodes[0],username=server_login,password=server_passphrase,key_filename=server_key)

    try:
        print "creating jobtracker mapred directories..."
        stdin,stdout,stderr = ssh.exec_command("sudo -u hdfs hdfs dfs -mkdir -p /tmp/mapred/system")
        wait_command(stdout,hdfs_datanodes[0])
        stdin,stdout,stderr = ssh.exec_command("sudo -u hdfs hdfs dfs -chown -R mapred:supergroup /tmp/mapred")
        wait_command(stdout,hdfs_datanodes[0])
    except:
        print "Failed to create mapred directories..."

    #restart mapreduce service
    print "Restarting mapreduce service..."
    cmd = mr.restart().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createYarn(cluster_name,api,configfile):
    print "Creating YARN Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['yarn']['service_name']
    jh_rolename = config['yarn']['jh_rolename']
    rm_rolename = config['yarn']['rm_rolename']
    nm_rolename = config['yarn']['nm_rolename']
    jh_server = config['yarn']['jh_server']
    rm_server = config['yarn']['rm_server']
    nm_server = config['yarn']['nm_server']
    hdfs_service = config['yarn']['service_config']['hdfs_service']
    yarn_nodemanager_local_dirs = config['yarn']['nodemanager']['yarn_nodemanager_local_dirs']

    yarn = cluster.create_service(service_name, "YARN")

    i = 1
    if isinstance(jh_server,basestring):
        yarn.create_role(jh_rolename,"JOBHISTORY", jh_server)
    else:
        for n in jh_server:
            yarn.create_role(jh_rolename+"-"+str(i),"JOBHISTORY", n)
            i += 1

    i = 1
    if isinstance(rm_server,basestring):
        yarn.create_role(rm_rolename,"RESOURCEMANAGER", rm_server)
    else:
        for n in rm_server:
            yarn.create_role(rm_rolename+"-"+str(i),"RESOURCEMANAGER", n)
            i += 1

    i = 1
    if isinstance(nm_server,basestring):
        yarn.create_role(nm_rolename,"NODEMANAGER", nm_server)
    else:
        for n in nm_server:
            yarn.create_role(nm_rolename+"-"+str(i),"NODEMANAGER", n)
            i += 1

    yarn.update_config(
            {'hdfs_service' : hdfs_service}
        )

    yarn_nm_groups = []
    for group in yarn.get_all_role_config_groups():
        if group.roleType == "NODEMANAGER":
            yarn_nm_groups.append(group)

    for name,config in yarn_nm_groups[0].get_config(view='full').items():
        yarn_nm_groups[0].update_config({
            'yarn_nodemanager_local_dirs':yarn_nodemanager_local_dirs
            })



    print "deploying client configuration.."
    cmd = cluster.deploy_client_config().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating yarn history directory..."
    cmd = yarn.create_yarn_job_history_dir().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating nodemanager remote application log directory..."
    cmd = yarn.create_yarn_node_manager_remote_app_log_dir().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Importing mapreduce configs into yarn..."
    cmd = yarn.import_mr_configs_into_yarn().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Successfully deployed YARN configs.."

    print "Starting Yarn service..."
    cmd = yarn.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)


def createSpark(cluster_name,api,configfile):
    print "Creating Spark Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return
    config = ConfigObj(configfile)
    service_name = config['spark']['service_name']
    hdfs_service = config['spark']['hdfs_service']
    spark_master_host = config['spark']['spark_master_host']
    spark_worker_host = config['spark']['spark_worker_host']
    spark_gateway_host = config['spark']['spark_gateway_host']
    spark_master_rolename = config['spark']['spark_master_rolename']
    spark_worker_rolename =  config['spark']['spark_worker_rolename']
    spark_gateway_rolename = config['spark']['spark_gateway_rolename']

    spark = cluster.create_service(service_name, "SPARK")
    spark_service_config = {
                            'hdfs_service': hdfs_service
                            }
    spark_master_config = { }
    spark_worker_config = { }
    spark_gateway_config = { }



    i = 1
    if isinstance(spark_master_host,basestring):
        spark.create_role(spark_master_rolename,"SPARK_MASTER", spark_master_host)
    else:
        for n in spark_master_host:
            spark.create_role(spark_master_rolename+"-"+str(i),"SPARK_MASTER", n)
            i += 1

    i = 1
    if isinstance(spark_worker_host,basestring):
        spark.create_role(spark_worker_rolename,"SPARK_WORKER", spark_worker_host)
    else:
        for n in spark_worker_host:
            spark.create_role(spark_worker_rolename+"-"+str(i),"SPARK_WORKER", n)
            i += 1

    i = 1
    if isinstance(spark_gateway_host,basestring):
        spark.create_role(spark_gateway_rolename,"GATEWAY", spark_gateway_host)
    else:
        for n in spark_gateway_host:
            spark.create_role(spark_gateway_rolename+"-"+str(i),"GATEWAY", n)
            i += 1


    spark.update_config(spark_service_config)



    spark_master_groups = []
    for group in spark.get_all_role_config_groups():
        if group.roleType == "SPARK_MASTER":
            spark_master_groups.append(group)

    for name,config in spark_master_groups[0].get_config(view='full').items():
        spark_master_groups[0].update_config(spark_master_config)

    spark_worker_groups = []
    for group in spark.get_all_role_config_groups():
        if group.roleType == "SPARK_WORKER":
            spark_worker_groups.append(group)

    for name,config in spark_worker_groups[0].get_config(view='full').items():
        spark_worker_groups[0].update_config(spark_worker_config)

    spark_gateway_groups = []
    for group in spark.get_all_role_config_groups():
        if group.roleType == "GATEWAY":
            spark_gateway_groups.append(group)

    for name,config in spark_gateway_groups[0].get_config(view='full').items():
        spark_gateway_groups[0].update_config(spark_gateway_config)


    print "deploying client configuration.."
    cmd = cluster.deploy_client_config().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting Spark service..."
    cmd = spark.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createImpala(cluster_name,api,configfile):
    print "Creating Impala Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return
    config = ConfigObj(configfile)
    service_name = config['impala']['service_name']
    hdfs_service = config['impala']['hdfs_service']
    hive_service = config['impala']['hive_service']
    impala_ss_host = config['impala']['impala_ss_host']
    impala_cs_host = config['impala']['impala_cs_host']
    impalad_hosts = config['impala']['impalad_hosts']
    impala_ss_rolename = config['impala']['impala_ss_rolename']
    impala_cs_rolename = config['impala']['impala_cs_rolename']
    impalad_rolename = config['impala']['impalad_rolename']

    impala_ss_config = { 'hdfs_service' : hdfs_service,
                         'hive_service' : hive_service
                     }
    impala_cs_config = { }
    impalad_config = { }

    impala = cluster.create_service(service_name, "IMPALA")
    impala.update_config(impala_ss_config)

    i = 1
    if isinstance(impala_ss_host,basestring):
        impala.create_role(impala_ss_rolename,"STATESTORE", impala_ss_host)
    else:
        for n in impala_ss_host:
            impala.create_role(impala_ss_rolename+"-"+str(i),"STATESTORE", n)
            i += 1

    i = 1
    if isinstance(impala_cs_host,basestring):
        impala.create_role(impala_cs_rolename,"CATALOGSERVER", impala_cs_host)
    else:
        for n in impala_cs_host:
            impala.create_role(impala_cs_rolename+"-"+str(i),"CATALOGSERVER", n)
            i += 1

    i = 1
    if isinstance(impalad_hosts,basestring):
        impala.create_role(impalad_rolename,"IMPALAD", impalad_hosts)
    else:
        for n in impalad_hosts:
            impala.create_role(impalad_rolename+"-"+str(i),"IMPALAD", n)
            i += 1

    print "Creating impala user directory..."
    cmd = impala.create_impala_user_dir().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting Impala service..."
    cmd = impala.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createSolr(cluster_name,api,configfile):
    print "Creating Solr service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return
    config = ConfigObj(configfile)
    service_name = config['solr']['service_name']
    search_solr_server = config['solr']['search_solr_server']
    search_gateway_server = config['solr']['search_gateway_server']
    search_solr_rolename = config['solr']['search_solr_rolename']
    search_gateway_rolename = config['solr']['search_gateway_rolename']
    hdfs_service = config['solr']['hdfs_service']
    zookeeper_service = config['solr']['zookeeper_service']
    search_service_config = {
                              'hdfs_service': hdfs_service,
                              'zookeeper_service': zookeeper_service
                            }
    search_solr_config = { }
    search_gateway_config = { }
    solr = cluster.create_service(service_name, "SOLR")
    solr.update_config(search_service_config)

    i = 1
    if isinstance(search_solr_server,basestring):
        solr.create_role(search_solr_rolename,"SOLR_SERVER", search_solr_server)
    else:
        for n in search_solr_server:
            solr.create_role(search_solr_rolename+"-"+str(i),"SOLR_SERVER", n)
            i += 1

    i = 1
    if isinstance(search_gateway_server,basestring):
        solr.create_role(search_gateway_rolename,"GATEWAY", search_gateway_server)
    else:
        for n in search_gateway_server:
            solr.create_role(search_gateway_rolename+"-"+str(i),"GATEWAY", n)
            i += 1



    solr_server_groups = []
    for group in solr.get_all_role_config_groups():
        if group.roleType == "SOLR_SERVER":
            solr_server_groups.append(group)
    for name,config in solr_server_groups[0].get_config(view='full').items():
        solr_server_groups[0].update_config(search_solr_config)

    solr_gateway_groups = []
    for group in solr.get_all_role_config_groups():
        if group.roleType == "GATEWAY":
            solr_gateway_groups.append(group)
    for name,config in solr_gateway_groups[0].get_config(view='full').items():
        solr_gateway_groups[0].update_config(search_gateway_config)

    print "Starting Solr service..."
    cmd = solr.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createFlume(cluster_name,api,configfile):
    print "Creating Flume Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['flume']['service_name']
    hdfs_service = config['flume']['hdfs_service']
    hbase_service = config['flume']['hbase_service']
    solr_service = config['flume']['solr_service']
    flume_agent_servers = config['flume']['flume_agent_servers']
    flume_agent_rolename = config['flume']['flume_agent_rolename']

    flume_service_config = {
        'hdfs_service': hdfs_service,
        'hbase_service': hbase_service,
        'solr_service': solr_service
    }
    flume_agent_config = { }

    flume = cluster.create_service(service_name, "FLUME")
    flume.update_config(flume_service_config)

    flume_agent_groups = []
    for group in flume.get_all_role_config_groups():
        if group.roleType == "AGENT":
            flume_agent_groups.append(group)

    for name,config in flume_agent_groups[0].get_config(view='full').items():
        flume_agent_groups[0].update_config(flume_agent_config)


    i = 1
    if isinstance(flume_agent_servers,basestring):
        flume.create_role(flume_agent_rolename,"AGENT", flume_agent_servers)
    else:
        for n in flume_agent_servers:
            flume.create_role(flume_agent_rolename+"-"+str(i),"AGENT", n)
            i += 1

    print "Starting Flume service..."
    cmd = flume.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)


def createOozie(cluster_name,api,configfile):
    print "Creating Oozie Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['oozie']['service_name']
    zookeeper_service = config['oozie']['zookeeper_service']
    oozie_servers = config['oozie']['oozie_servers']
    oozie_servers_rolename = config['oozie']['oozie_servers_rolename']
    hive_metastore_database_host = config['hive']['config']['hive_metastore_database_host']
    hive_metastore_password = config['hive']['config']['hive_metastore_database_password']
    yarn_service = config['yarn']['service_name']

    oozie_service_config = {
                'mapreduce_yarn_service': yarn_service,
                'zookeeper_service': zookeeper_service,
    }
    oozie_server_config = {
       'oozie_java_heapsize': 207881018,
       'oozie_database_host': hive_metastore_database_host,
       'oozie_database_name': 'oozie',
       'oozie_database_password': hive_metastore_password,
       'oozie_database_type': 'mysql',
       'oozie_database_user': 'oozie',
    }

    oozie = cluster.create_service(service_name, "OOZIE")
    oozie.update_config(oozie_service_config)

    oozie_server_groups = []
    for group in oozie.get_all_role_config_groups():
        if group.roleType == "OOZIE_SERVER":
            oozie_server_groups.append(group)

    for name,config in oozie_server_groups[0].get_config(view='full').items():
        oozie_server_groups[0].update_config(oozie_server_config)


    i = 1
    if isinstance(oozie_servers,basestring):
        oozie.create_role(oozie_servers_rolename,"OOZIE_SERVER", oozie_servers)
    else:
        for n in oozie_servers:
            oozie.create_role(oozie_servers_rolename+"-"+str(i),"OOZIE_SERVER", n)
            i += 1

#    print "Install oozie database..."
#    cmd = oozie.create_oozie_db().wait()
#    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Install oozie sharelib..."
    cmd = oozie.install_oozie_sharelib().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting Ozzie service..."
    cmd = oozie.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createSqoop(cluster_name,api,configfile):
    print "Creating Sqoop service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['sqoop']['service_name']
    sqoop_server = config['sqoop']['sqoop_server']
    sqoop_server_rolename = config['sqoop']['sqoop_server_rolename']
    yarn_service = config['yarn']['service_name']

    sqoop_service_config = {
        'mapreduce_yarn_service': yarn_service,
    }
    sqoop_server_config = {
        'sqoop_java_heapsize': 207881018,
    }

    sqoop = cluster.create_service(service_name, "SQOOP")
    sqoop.update_config(sqoop_service_config)

    sqoop_server_groups = []
    for group in sqoop.get_all_role_config_groups():
        if group.roleType == "SQOOP_SERVER":
            sqoop_server_groups.append(group)

    for name,config in sqoop_server_groups[0].get_config(view='full').items():
        sqoop_server_groups[0].update_config(sqoop_server_config)

    if isinstance(sqoop_server,basestring):
        sqoop.create_role(sqoop_server_rolename,"SQOOP_SERVER", sqoop_server)
    else:
        i = 0
        for n in sqoop_server:
            sqoop.create_role(sqoop_server_rolename+"-"+str(i),"SQOOP_SERVER", n)
            i = i + 1

    print "Starting Scoop service..."
    cmd = sqoop.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Successfully deployed sqoop service..."


def createHue(cluster_name,api,configfile):
    print "Creating Hue service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['hue']['service_name']
    hue_server = config['hue']['hue_server']
    search_solr_server = config['solr']['search_solr_server']
    hue_server_rolename = config['hue']['hue_server_rolename']
    hue_ktr_server = config['hue']['hue_ktr_server']
    hue_ktr_rolename = config['hue']['hue_ktr_rolename']
    hive_service = config['hive']['service_name']
    hbase_service = config['hbase']['service_name']
    hbase_thrift_service_name = config['hbase']['hb_thriftserver_rolename']
    impala_service = config['impala']['service_name']
    oozie_service = config['oozie']['service_name']
    sqoop_service = config['sqoop']['service_name']
    hdfs_service = config['hdfs']['service_name']
    name_node_service_name = config['hdfs']['name_node_service_name']


    hue_service_config = {
        'hive_service': hive_service,
        'hbase_service': hbase_service,
        'impala_service': impala_service,
        'oozie_service': oozie_service,
        'sqoop_service': sqoop_service,
        'hue_webhdfs': name_node_service_name,
        'hue_hbase_thrift': hbase_thrift_service_name,
    }

    hue_server_config = {
        'hue_server_hue_safety_valve': '[search]\r\n## URL of the Solr Server\r\nsolr_url=http://' + search_solr_server + ':8983/solr',

    }

    hue_ktr_config = { }

    hue = cluster.create_service(service_name, "HUE")
    hue.update_config(hue_service_config)

    hue_server_groups = []
    for group in hue.get_all_role_config_groups():
        if group.roleType == "HUE_SERVER":
            hue_server_groups.append(group)

    for name,config in hue_server_groups[0].get_config(view='full').items():
        hue_server_groups[0].update_config(hue_server_config)

    if isinstance(hue_server,basestring):
        hue.create_role(hue_server_rolename,"HUE_SERVER", hue_server)
    else:
        i = 0
        for n in hue_server:
            hue.create_role(hue_server_rolename+"-"+str(i),"HUE_SERVER", n)
            i = i + 1

    print "Starting Hue service..."
    cmd = hue.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Successfully deployed Hue service..."


def createHive(cluster_name,api,configfile):
    print "Creating Hive Service..."
    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['hive']['service_name']
    zookeeper_service = config['zookeeper']['service_name']
    yarn_service = config['yarn']['service_name']
    ms_rolename = config['hive']['ms_rolename']
    wc_rolename = config['hive']['wc_rolename']
    hs_rolename = config['hive']['hs_rolename']
    gw_rolename = config['hive']['gw_rolename']
    ms_nodes    = config['hive']['ms_nodes']
    wc_nodes    = config['hive']['wc_nodes']
    hs_nodes    = config['hive']['hs_nodes']
    gw_nodes    = config['hive']['gw_nodes']
    hm_warehouse_dir = config['hive']['config']['hive_warehouse_directory']
    hm_db_name  = config['hive']['config']['hive_metastore_database_name']
    hm_db_host  = config['hive']['config']['hive_metastore_database_host']
    hm_db_user  = config['hive']['config']['hive_metastore_database_user']
    hm_db_pwd   = config['hive']['config']['hive_metastore_database_password']
    hm_db_port  = config['hive']['config']['hive_metastore_database_port']
    hm_db_type  = config['hive']['config']['hive_metastore_database_type']
    server_login = config['cluster']['server_login']
    server_passwd = config['cluster']['server_passwd']
    server_key = config['cluster']['server_key']
    server_passphrase = config['cluster']['server_passphrase']
    hdfs_datanodes = config['hdfs']['data_nodes']

    hiveserver2_config = {
             'oom_heap_dump_dir': '/hive/tmp'}

    hive = cluster.create_service(service_name, "HIVE")
    if isinstance(ms_nodes,basestring):
        hive.create_role(ms_rolename,"HIVEMETASTORE", ms_nodes)
    else:
        i = 0
        for n in ms_nodes:
            hive.create_role(ms_rolename+"-"+str(i),"HIVEMETASTORE", n)
            i = i + 1

    if isinstance(wc_nodes,basestring):
        hive.create_role(wc_rolename,"WEBHCAT", wc_nodes)
    else:
        i = 0
        for n in wc_nodes:
            hive.create_role(wc_rolename+"-"+str(i),"WEBHCAT", n)
            i = i + 1

    if isinstance(hs_nodes,basestring):
        hive.create_role(hs_rolename,"HIVESERVER2", hs_nodes)
    else:
        i = 0
        for n in hs_nodes:
            hive.create_role(hs_rolename+"-"+str(i),"HIVESERVER2", n)
            i = i + 1

    if isinstance(gw_nodes,basestring):
        hive.create_role(gw_rolename,"GATEWAY", gw_nodes)
    else:
        i = 0
        for n in gw_nodes:
            hive.create_role(gw_rolename+"-"+str(i),"GATEWAY", n)
            i = i + 1



    hive.update_config(
            {'mapreduce_yarn_service' : yarn_service,
             'hive_warehouse_directory' : hm_warehouse_dir,
             'zookeeper_service': zookeeper_service,
             'hive_metastore_database_type' : hm_db_type,
             'hive_metastore_database_name' : hm_db_name,
             'hive_metastore_database_host' : hm_db_host,
             'hive_metastore_database_user' : hm_db_user,
             'hive_metastore_database_password' : hm_db_pwd,
             'hive_metastore_database_port' : hm_db_port
             }
        )

    hive_server_groups = []
    for group in hive.get_all_role_config_groups():
        if group.roleType == "HIVESERVER2":
            hive_server_groups.append(group)

    for name,config in hive_server_groups[0].get_config(view='full').items():
        hive_server_groups[0].update_config(hiveserver2_config)

    #create hive directory
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if server_key == "None":
        ssh.connect(hdfs_datanodes[0],username=server_login,password=server_passwd)
    else:
        ssh.connect(hdfs_datanodes[0],username=server_login,password=server_passphrase,key_filename=server_key)

    try:
        print "creating hive tmp directory..."
        stdin,stdout,stderr = ssh.exec_command("sudo -u hdfs hdfs dfs -mkdir -p /hive/tmp")
        wait_command(stdout,hdfs_datanodes[0])
        stdin,stdout,stderr = ssh.exec_command("sudo -u hdfs hdfs dfs -chown -R hive:supergroup /hive")
        wait_command(stdout,hdfs_datanodes[0])
    except:
        print "Failed to create hive tmp directories..."

    print "deploying client configuration.."
    cmd = cluster.deploy_client_config().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating hive user directory..."
    cmd = hive.create_hive_userdir().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating hive warehouse directory.."
    cmd = hive.create_hive_warehouse().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating hive metastore database.."
    cmd = hive.create_hive_metastore_database().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Creating hive metastore tables.."
    cmd = hive.create_hive_metastore_tables().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Updating hive metastore namenodes..."
    cmd = hive.update_hive_metastore_namenodes().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Upgrading hive metatore tables..."
    cmd = hive.upgrade_hive_metastore().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting Hive service..."
    cmd = hive.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createZookeeper(cluster_name,api,configfile):
    print "Creating Zookeeper Service..."

    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['zookeeper']['service_name']
    zookeeper_servers = config['zookeeper']['zk_servers']
    zk_rolename = config['zookeeper']['zk_rolename']
    zookeeper_service_config = {
        'zookeeper_datadir_autocreate': 'true',
    }
    zookeeper_server_config = {
    'quorumPort': 2888,
    'electionPort': 3888,
    'dataLogDir': '/var/lib/zookeeper',
    'dataDir': '/var/lib/zookeeper',
    'maxClientCnxns': '1024',
    }

    zookeeper = cluster.create_service(service_name, "ZOOKEEPER")
    zookeeper.update_config(zookeeper_service_config)

    i = 1
    if isinstance(zookeeper_servers,basestring):
        zookeeper.create_role(zk_rolename,"SERVER", zookeeper_servers)
    else:
        for n in zookeeper_servers:
            zookeeper.create_role(zk_rolename+"-"+str(i),"SERVER", n)
            i += 1

    zookeeper_server_groups = []
    for group in zookeeper.get_all_role_config_groups():
        if group.roleType == "SERVER":
            zookeeper_server_groups.append(group)

    for name,config in zookeeper_server_groups[0].get_config(view='full').items():
        zookeeper_server_groups[0].update_config(zookeeper_server_config)



    print "deploying client configuration.."
    cmd = cluster.deploy_client_config().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "initializing Zookeeper service.."
    cmd = zookeeper.init_zookeeper().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting zookeeper service..."
    cmd = zookeeper.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

def createHbase(cluster_name,api,configfile):
    print "Creating Hbase Service..."

    for c in api.get_all_clusters():
        if c.name == cluster_name:
            cluster = c
        else:
            print "cluster does not exist"
            return

    config = ConfigObj(configfile)
    service_name = config['hbase']['service_name']
    hb_restserver_rolename = config['hbase']['hb_restserver_rolename']
    hb_regionserver_rolename = config['hbase']['hb_regionserver_rolename']
    hb_master_rolename = config['hbase']['hb_master_rolename']
    hb_thriftserver_rolename = config['hbase']['hb_thriftserver_rolename']

    hb_restserver = config['hbase']['hb_restserver']
    hb_regionserver = config['hbase']['hb_regionserver']
    hb_master = config['hbase']['hb_master']
    hb_thriftserver = config['hbase']['hb_thriftserver']
    hdfs_service = config['hbase']['hb_hdfs_service']
    zookeeper_service = config['hbase']['hb_zookeeper_service']
    hdfs_rootdir = config['hbase']['hb_hdfs_rootdir']

    hbase = cluster.create_service(service_name, "HBASE")

    if isinstance(hb_restserver,basestring):
        hbase.create_role(hb_restserver_rolename,"HBASERESTSERVER", hb_restserver)
    else:
        i = 0
        for n in hb_restserver:
            hbase.create_role(hb_restserver_rolename+"-"+str(i),"HBASERESTSERVER",n)
            i += 1


    if isinstance(hb_regionserver,basestring):
        hbase.create_role(hb_regionserver_rolename,"REGIONSERVER", hb_regionserver)
    else:
        i = 0
        for n in hb_regionserver:
            hbase.create_role(hb_regionserver_rolename+"-"+str(i),"REGIONSERVER",n)
            i += 1

    if isinstance(hb_master,basestring):
        hbase.create_role(hb_master_rolename,"MASTER", hb_master)
    else:
        i = 0
        for n in hb_master:
            hbase.create_role(hb_master_rolename+"-"+str(i),"MASTER",n)
            i += 1

    if isinstance(hb_thriftserver,basestring):
        hbase.create_role(hb_thriftserver_rolename,"HBASETHRIFTSERVER", hb_thriftserver)
    else:
        i = 0
        for n in hb_thriftserver:
            hbase.create_role(hb_thriftserver_rolename+"-"+str(i),"HBASETHRIFTSERVER",n)
            i += 1


    hbase.update_config(
        {
            'hdfs_service': hdfs_service,
            'zookeeper_service': zookeeper_service,
            'hdfs_rootdir': hdfs_rootdir
        }
    )

    print "Creating root directory..."
    cmd = hbase.create_hbase_root().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "deploying client configuration.."
    cmd = cluster.deploy_client_config().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    print "Starting hbase service..."
    cmd = hbase.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)


def parcelMain(cluster_name,api,cloudera_parcel_repo):
    # replace parcel_repo with the parcel repo you want to use
    print "Updating parcel repo"
    #parcel_repo = 'http://archive.cloudera.com/cdh5/parcels/5.0.0/'
    parcel_repo = cloudera_parcel_repo
    cm_config = api.get_cloudera_manager().get_config(view='full')
    repo_config = cm_config['REMOTE_PARCEL_REPO_URLS']
    value = repo_config.value or repo_config.default
    # value is a comma-separated list
    value += ',' + parcel_repo
    api.get_cloudera_manager().update_config({
      'REMOTE_PARCEL_REPO_URLS': value})
    # wait to make sure parcels are refreshed
    time.sleep(25)

    #download the parcel to the CM server
    # replace cluster_name with the name of your cluster
    #cluster_name = 'clusterX'
    cluster = api.get_cluster(cluster_name)
    # replace parcel_version with the specific parcel version you want to install
    # After adding your parcel repository to CM, you can use the API to list all parcels and get the precise version string by inspecting:
    # cluster.get_all_parcels() or looking at the URL http://<cm_host>:7180/api/v5/clusters/<cluster_name>/parcels/
    parcel_version = cluster.get_all_parcels()[0].version

    #parcel_version = '5.0.0-1.cdh5.0.0.p0.47'
    parcel = cluster.get_parcel('CDH', parcel_version)
    print "Downloading parcel to the CM server..."
    parcel.start_download()
    # unlike other commands, check progress by looking at parcel stage and status

    while True:
        parcel = cluster.get_parcel('CDH', parcel_version)
        if parcel.stage == 'DOWNLOADED':
            break
        if parcel.state.errors:
            raise Exception(str(parcel.state.errors))
        print "progress: %s / %s" % (parcel.state.progress, parcel.state.totalProgress)
        time.sleep(25) # check again in 15 seconds

    print "downloaded CDH parcel version %s on cluster %s" % (parcel_version, cluster_name)

    #Distribute the parcel
    print "Distributing parcel across the cluster...."
    parcel.start_distribution()
    while True:
        parcel = cluster.get_parcel('CDH', parcel_version)
        if parcel.stage == 'DISTRIBUTED':
            break
        if parcel.state.errors:
            raise Exception(str(parcel.state.errors))
        print "progress: %s / %s" % (parcel.state.progress, parcel.state.totalProgress)
        time.sleep(15) # check again in 15 seconds

    print "distributed CDH parcel version %s on cluster %s" % (parcel_version, cluster_name)

    print "Activating Parcel.."
    parcel.activate()

    print "Stopping cluster..."
    cluster.stop().wait()
    print "Cluster stopped...."
    print "Starting cluster.."
    cluster.start().wait()
    print "Cluster started..."

    print "Deploy client configuration on the hosts..."
    cluster.deploy_client_config().wait()
    print "Client configuration successfully deployed..."


def createMGMT(api,cm_hostname,server_login,server_passwd,server_passphrase,server_key):
    #get alert monitor passwd
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if server_key == "None":
        ssh.connect(cm_hostname,username=server_login,password=server_passwd)
    else:
        ssh.connect(cm_hostname,username=server_login,password=server_passphrase,key_filename=server_key)


    try:
        stdin,stdout,stderr = ssh.exec_command("grep \"ACTIVITYMONITOR.db.password\" /etc/cloudera-scm-server/db.mgmt.properties | awk -F\'=\' \'{print $2}\'")
        for i in stdout.readlines():
            am_passwd = i.rstrip("\n")
            print am_passwd
    except:
        print "cannot get activity monitor db password..."

    cm = api.get_cloudera_manager()
    print "Creating management service...."
    mgmt = cm.create_mgmt_service(ApiServiceSetupInfo())

    print "Role ACTIVITYMONITOR created"
    mgmt.create_role("mgmt-am", "ACTIVITYMONITOR", cm_hostname)
    print "Role ALERTPUBLISHER created"
    mgmt.create_role("mgmt-ap", "ALERTPUBLISHER", cm_hostname)
    print "Role EVENTSERVER created"
    mgmt.create_role("mgmt-es", "EVENTSERVER", cm_hostname)
    print "Role HOSTMONITOR created"
    mgmt.create_role("mgmt-hm", "HOSTMONITOR", cm_hostname)
    print "Role SERVICEMONITOR created"
    mgmt.create_role("mgmt-sm", "SERVICEMONITOR", cm_hostname)

    mgmt_service_config = {
        'zookeeper_datadir_autocreate': 'true',
    }
    am_config = {
        'firehose_database_host': cm_hostname + ":7432",
        'firehose_database_user': 'amon',
        'firehose_database_password': am_passwd,
        'firehose_database_type': 'postgresql',
        'firehose_database_name': 'amon',
        'firehose_heapsize': '215964392',
        }

    sm_config = {
        'firehose_storage_dir': '/var/lib/cloudera-service-monitor',
        'firehose_heapsize': '209715200',
        'firehose_non_java_memory_bytes': '805306368',
        }

    hm_config = {
        'mgmt_log_dir': '/var/log/cloudera-scm-firehose',
        'firehose_storage_dir': '/var/lib/cloudera-host-monitor',
        'firehose_heapsize': '209715200',
        'firehose_non_java_memory_bytes': '805306368',
        }

    es_config = {
        'event_server_heapsize': '215964392'
        }

    ap_config = {
        'firehose_database_host': cm_hostname,
        'firehose_database_user': 'amon',
        'firehose_database_password': 'inY8pAB5T2',
        'firehose_database_type': 'postgresql',
        'firehose_database_name': 'amon',
        'firehose_heapsize': '215964392',
        }
    ap_config = { }

    for group in mgmt.get_all_role_config_groups():
        if group.roleType == "ACTIVITYMONITOR":
            print "updating ACTIVITYMONITOR configs..."
            group.update_config(am_config)
        elif group.roleType == "ALERTPUBLISHER":
            group.update_config(ap_config)
        elif group.roleType == "EVENTSERVER":
            print "updating EVENTSERVER configs..."
            group.update_config(es_config)
        elif group.roleType == "HOSTMONITOR":
            print "updating HOSTMONITOR configs..."
            group.update_config(hm_config)
        elif group.roleType == "SERVICEMONITOR":
            print "updating SERVICEMONITOR configs..."
            group.update_config(sm_config)

    print "Starting management service..."
    cmd = mgmt.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)


def main():
    configfile=''

    if len(sys.argv) > 3 or len(sys.argv) < 3:
        print("Usage: %s -i configfile " % sys.argv[0])
        sys.exit(2)

    try:
        myopts, args = getopt.getopt(sys.argv[1:],"i:h")
    except getopt.GetoptError as e:
        print (str(e))
        print("Usage: %s -i configfile " % sys.argv[0])
        sys.exit(2)

    for o, a in myopts:
        if o == '-i':
            configfile=a
        elif o == '-h':
            print("Usage: %s -i configfile " % sys.argv[0])

    if os.path.isfile(configfile):
        print "processing configuration file...."
        pass
    else:
        print "file does not exist..."
        sys.exit(2)


    config = ConfigObj(configfile)
    cluster_name = config['cluster']['name']
    cdh_manager = config['cluster']['cdh_manager']
    cm_hostname = config['cluster']['cm_hostname']
    hostnames = config['cluster']['server_hostnames']
    services = config['cluster']['services']
    server_rack = config['cluster']['server_rack']
    server_login = config['cluster']['server_login']
    server_passwd = config['cluster']['server_passwd']
    server_key = config['cluster']['server_key']
    server_passphrase = config['cluster']['server_passphrase']
    cloudera_manager_repo = config['cluster']['cloudera_manager_repo']

    cm_host = cdh_manager
    api = ApiResource(cm_host, username="admin", password="admin")
    #print config['hive']['config']['hive_metastore_database_name']


    for c in api.get_all_clusters():
        if c.name == cluster_name:
            #cluster = c
            print "Cluster %s already exists " % (cluster_name)
            print "Please manually delete the cluster %s , all hosts and associated services." % (cluster_name)
            sys.exit(0)
        else:
            print "Starting the automation process..."

            pass


    cdhproc(cluster_name,api,hostnames,server_rack,server_login,server_passwd,server_key,server_passphrase,cloudera_manager_repo)
    createMGMT(api,cm_hostname,server_login,server_passwd,server_passphrase,server_key)
    deployHDFSMAP(cluster_name,api,configfile)

    if "yarn" in services:
        createYarn(cluster_name,api,configfile)
    if "zookeeper" in services:
        createZookeeper(cluster_name,api,configfile)
    if "hive" in services:
        createHive(cluster_name,api,configfile)
    if "hbase" in services:
        createHbase(cluster_name,api,configfile)
    if "spark" in services:
        createSpark(cluster_name,api,configfile)
    if "impala" in services:
        createImpala(cluster_name,api,configfile)

    cluster = api.get_cluster(cluster_name)

    print "Stopping cluster..."
    cmd = cluster.stop().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)
    print "Starting cluster..."
    cmd =cluster.start().wait()
    print "Active: %s. Success: %s" % (cmd.active, cmd.success)

    if "solr" in services:
        createSolr(cluster_name,api,configfile)
    if "flume" in services:
        createFlume(cluster_name,api,configfile)
    if "oozie" in services:
        createOozie(cluster_name,api,configfile)
    if "sqoop" in services:
        createSqoop(cluster_name,api,configfile)
    if "hue" in services:
        createHue(cluster_name,api,configfile)

    #print "Stopping cluster..."
    #cmd = cluster.stop().wait()
    #print "Active: %s. Success: %s" % (cmd.active, cmd.success)
    #print "Starting cluster..."
    #cmd =cluster.start().wait
    #print "Active: %s. Success: %s" % (cmd.active, cmd.success)


    print "Cluster deployed successfully...."
    print "Login to: http://"+cdh_manager+":7180"

if __name__ == "__main__":
    main()


