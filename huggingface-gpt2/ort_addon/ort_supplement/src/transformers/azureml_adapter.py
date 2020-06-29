import os


def set_environment_variables_for_nccl_backend(single_node=False, master_port=6105):
    os.environ['RANK'] = os.environ['OMPI_COMM_WORLD_RANK']
    os.environ['WORLD_SIZE'] = os.environ['OMPI_COMM_WORLD_SIZE']

    if not single_node: 
        master_node_params = os.environ['AZ_BATCH_MASTER_NODE'].split(':')
        os.environ['MASTER_ADDR'] = master_node_params[0]

        # Do not overwrite master port with that defined in AZ_BATCH_MASTER_NODE
        if 'MASTER_PORT' not in os.environ:
            os.environ['MASTER_PORT'] = str(master_port)
    else:
        os.environ['MASTER_ADDR'] = os.environ['AZ_BATCHAI_MPI_MASTER_NODE']
        os.environ['MASTER_PORT'] = '54965'
    print('NCCL_SOCKET_IFNAME original value = {}'.format(os.environ['NCCL_SOCKET_IFNAME']))
    # TODO make this parameterizable
    os.environ['NCCL_SOCKET_IFNAME'] = '^docker0,lo'

    print('RANK = {}'.format(os.environ['RANK']))
    print('WORLD_SIZE = {}'.format(os.environ['WORLD_SIZE']))
    print('MASTER_ADDR = {}'.format(os.environ['MASTER_ADDR']))
    print('MASTER_PORT = {}'.format(os.environ['MASTER_PORT']))
    # print('MASTER_NODE = {}'.format(os.environ['MASTER_NODE']))
    print('NCCL_SOCKET_IFNAME new value = {}'.format(os.environ['NCCL_SOCKET_IFNAME']))

def get_local_rank():
    return int(os.environ['OMPI_COMM_WORLD_LOCAL_RANK'])

def get_global_size():
    return int(os.environ['OMPI_COMM_WORLD_SIZE'])

def get_local_size():
    return int(os.environ['OMPI_COMM_WORLD_LOCAL_SIZE'])	

def get_world_size():
    return int(os.environ['WORLD_SIZE'])

def get_world_rank():
    return int(os.environ['RANK'])