import os,resource,sys
resource.setrlimit(resource.RLIMIT_AS,(1100*1024**2,1100*1024**2))
resource.setrlimit(resource.RLIMIT_CPU,(90,90))
resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024**2,64*1024**2))
resource.setrlimit(resource.RLIMIT_CORE,(0,0))
os.execvp(sys.argv[1],sys.argv[1:])
