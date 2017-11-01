import logging,os,sys,importlib
logger = logging.getLogger(__name__)
from pandayoda.common import StatefulService,VariableWithLock,exceptions

config_section = os.path.basename(__file__)[:os.path.basename(__file__).rfind('.')]

class RequestHarvesterJob(StatefulService.StatefulService):
   ''' This thread is spawned to request jobs from Harvester '''

   CREATED              = 'CREATED'
   REQUEST              = 'REQUEST'
   WAITING              = 'WAITING'
   EXITED               = 'EXITED'

   STATES = [CREATED,REQUEST,WAITING,EXITED]
   RUNNING_STATES = [REQUEST,WAITING]

   def __init__(self,config):
      super(RequestHarvesterJob,self).__init__()

      # local config options
      self.config             = config

      # set current state of the thread to IDLE
      self.state              = VariableWithLock.VariableWithLock(self.IDLE)

      # if in state REQUEST_COMPLETE, this variable holds the job retrieved
      self.new_jobs           = VariableWithLock.VariableWithLock()

      # set if there are no more jobs coming from Harvester
      self.no_more_jobs_flag  = VariableWithLock.VariableWithLock(False)

      # start in the requesting state
      self.set_state(self.CREATED)


   def get_jobs(self):
      ''' parent thread calls this function to retrieve the jobs sent by Harevester '''
      jobs = self.new_jobs.get()
      return jobs
   def set_jobs(self,job_descriptions):
      self.new_jobs.set(job_descriptions)

   def exited(self):
      return self.in_state(self.EXITED)

   def running(self):
      if self.get_state() is in self.RUNNING_STATES:
         return True
      return False

   def no_more_jobs(self):
      return self.no_more_jobs_flag.get()

   def get_messenger(self):
      # get the name of the plugin from the config file
      if self.config.has_option(config_section,'messenger_plugin_module'):
         messenger_plugin_module = self.config.get(config_section,'messenger_plugin_module')
      else:
         raise Exception('Failed to retrieve messenger_plugin_module from config file section %s' % (config_section))


      # try to import the module specified in the config
      # if it is not in the PYTHONPATH this will fail
      try:
         return importlib.import_module(messenger_plugin_module)
      except ImportError:
         logger.exception('Failed to import messenger_plugin: %s',messenger_plugin_module)
         raise


   def run(self):
      ''' overriding base class function '''

      # get the messenger for communicating with Harvester
      messenger = self.get_messenger()
      messenger.setup(self.config)
      
      # read in loop_timeout
      if self.config.has_option(config_section,'loop_timeout'):
         messenger_plugin_module = self.config.get(config_section,'loop_timeout')

      # start in the request state
      self.set_state(self.REQUEST)

      while not self.exit.wait(timeout=self.loop_timeout):
         # get state
         logger.debug('start loop, current state: %s',self.get_state())
         
         #########
         # REQUEST State
         ########################
         if self.get_state() == self.REQUEST:
            logger.debug('making request for job')
            try:
               # use messenger to request jobs from Harvester
               messenger.request_jobs()
            except exceptions.MessengerJobAlreadyRequested:
               logger.warning('job already requested.')

            # wait for events
            self.set_state(self.WAITING)
         

         #########
         # REQUESTING State
         ########################
         elif self.get_state() == self.WAITING:
            logger.debug('checking if request is complete')
            # use messenger to check if jobs are ready
            if messenger.pandajobs_ready():
               logger.debug('jobs are ready')
               # use messenger to get jobs from Harvester
               pandajobs = messenger.get_pandajobs()
               
               # set jobs for parent and change state
               if len(pandajobs) > 0:
                  logger.debug('setting NEW_JOBS variable')
                  self.set_jobs(pandajobs)
                  self.stop()
               else:
                  logger.debug('no jobs returned: %s',pandajobs)
                  self.stop()
            else:
               logger.debug('no jobs ready yet.')

         else:
            logger.debug('nothing to do')
         

      self.set_state(self.EXITED)
      logger.debug('RequestHarvesterJob thread is exiting')
