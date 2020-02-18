
__all__ = ['TEventLoop']

from Gaugi.messenger import Logger, LoggingLevel
from Gaugi.messenger.macros import *
from Gaugi import StatusCode,StatusTool,StatusWTD
from Gaugi.gtypes import NotSet

# Import all root classes
try:
  import ROOT
except:
  pass
  #print ('WARNING: ROOT not found. You will not be able to use the TEventLoop services provied by the gaugi core.')


class TEventLoop( Logger ):

  def __init__(self, name, **kw):

    # Retrieve all information needed
    Logger.__init__(self, **kw)
    from Gaugi import retrieve_kw
    self._fList      = retrieve_kw( kw, 'inputFiles', NotSet                          )
    self._ofile      = retrieve_kw( kw, 'outputFile', "histos.root"                   )
    self._treePath   = retrieve_kw( kw, 'treePath'  , NotSet                          )
    self._dataframe  = retrieve_kw( kw, 'dataframe' , NotSet                          )
    self._nov        = retrieve_kw( kw, 'nov'       , -1                              )
    self._mute_progressbar   = retrieve_kw( kw, 'mute_progressbar', False             )
    self._level = LoggingLevel.retrieve( retrieve_kw(kw, 'level', LoggingLevel.INFO ) )
    self._name       = name
    if self._fList:
      from Gaugi import csvStr2List, expandFolders
      self._fList = csvStr2List ( self._fList )
      self._fList = expandFolders( self._fList )


    import collections
    self._containersSvc  = collections.OrderedDict() # container dict to hold all EDMs
    self._storegateSvc = None # storegate service to hold all hists
    self._t = NotSet # TChain used to hold the ttree files
    self._event = NotSet # TEvent schemma used to read the ttree
    self._entries = NotSet # total number of event inside of the ttree
    self._context = NotSet # Hold the event context

  def name(self):
    return self._name


  # Initialize all services
  def initialize( self ):

    MSG_INFO( self, 'Initializing TEventLoop...')

    # Use this to hold the fist good
    metadataInputFile = None
    from Gaugi import progressbar
    ### Prepare to loop:
    self._t = ROOT.TChain()
    for inputFile in progressbar(self._fList, len(self._fList), prefix= "Creating collection tree ", logger=self._logger):
      # Check if file exists
      self._f  = ROOT.TFile.Open(inputFile, 'read')
      if not self._f or self._f.IsZombie():
        MSG_WARNING( self, 'Couldn''t open file: %s', inputFile)
        continue
      # Inform user whether TTree exists, and which options are available:
      self._logger.debug("Adding file: %s", inputFile)
      try:
        # Custon directory token
        if '*' in self._treePath:
          dirname = self._f.GetListOfKeys()[0].GetName()
          treePath = self._treePath.replace('*',dirname)
        else:
          treePath=self._treePath
      except:
        MSG_WARNING( self, "Couldn't retrieve TTree (%s) from GetListOfKeys!", treePath)
        continue

      obj = self._f.Get(treePath)
      if not obj:
        MSG_WARNING( self, "Couldn't retrieve TTree (%s)!", treePath)
        MSG_INFO( self, "File available info:")
        self._f.ReadAll()
        self._f.ReadKeys()
        self._f.ls()
        continue
      elif not isinstance(obj, ROOT.TTree):
        MSG_FATAL( self, "%s is not an instance of TTree!", treePath, ValueError)
      self._t.Add( inputFile+'/'+treePath )
    # Turn all branches off.
    self._t.SetBranchStatus("*", False)

    # Ready to retrieve the total number of events
    self._t.GetEntry(0)
    ## Allocating memory for the number of entries
    self._entries = self._t.GetEntries()


    from Gaugi import EventContext
    self._context = EventContext(self._t)


    # Create the StoreGate service
    if not self._storegateSvc:
      MSG_INFO( self, "Creating StoreGate...")
      from Gaugi.storage import StoreGate
      self._storegateSvc = StoreGate( self._ofile , level = self._level)
    else:
      MSG_INFO( self, 'The StoraGate was created for ohter service. Using the service setted by client.')



    MSG_INFO( self, 'Initializing all tools...')
    from Gaugi import ToolSvc as toolSvc
    self._alg_tools = toolSvc.getTools()
    for alg in self._alg_tools:
      if alg.status is StatusTool.DISABLE:
        continue
      # Retrieve all services
      alg.level = self._level
      alg.setContext( self.getContext() )
      alg.setStoreGateSvc( self.getStoreGateSvc() )
      alg.dataframe = self._dataframe
      if alg.isInitialized():
        continue
      if alg.initialize().isFailure():
        MSG_FATAL( self, "Impossible to initialize the tool name: %s",alg.name)



    return StatusCode.SUCCESS




  def execute( self ):
    # retrieve values
    entries = self.getEntries()
    ### Loop over events
    from Gaugi import progressbar
    if not self._mute_progressbar:
      step = int(entries/100) if int(entries/100) > 0 else 1
      for entry in progressbar(range(self._entries), entries, step=step, prefix= "Looping over entries ", logger=self._logger):
        if self.nov < entry:
          break
        self.process(entry)
    else:
      for entry in range(self._entries):
        if self.nov < entry:
          break
        self.process(entry)
    return StatusCode.SUCCESS


  def process(self, entry):
    # retrieve all values from the branches
    context = self.getContext()
    context.setEntry(entry)
    # reading all values from file to EDM pointers.
    # the context hold all EDM pointers
    context.execute()
    # loop over tools...
    for alg in self._alg_tools:
      if alg.status is StatusTool.DISABLE:
        continue
      if alg.execute( context ).isFailure():
        MSG_ERROR( self, 'The tool %s return status code different of SUCCESS',alg.name)
      if alg.wtd is StatusWTD.ENABLE:
        self._logger.debug('Watchdog is true in %s. Skip events',alg.name)
        # reset the watchdog since this was used
        alg.wtd = StatusWTD.DISABLE
        break


  def finalize( self ):
    MSG_INFO( self, 'Finalizing all tools...')
    for alg in self._alg_tools:
      if alg.isFinalized():
        continue
      if alg.finalize().isFailure():
        MSG_ERROR( self, 'The tool %s return status code different of SUCCESS',alg.name)

    MSG_INFO( self, 'Finalizing StoreGate service...')
    self._storegateSvc.write()
    del self._storegateSvc
    MSG_DEBUG( self, "Finalizing file...")
    self._f.Close()
    del self._f
    del self._event
    del self._t
    MSG_DEBUG( self, "Everything was finished... tchau!")
    return StatusCode.SUCCESS



  def run( self, nov=-1 ):
    self._nov = nov
    self.initialize()
    self.execute()
    self.finalize()



  def getEntries(self):
    return self._entries

  # User method
  def getEntry( self, entry ):
    self._t.GetEntry( entry )



  def getContext(self):
    return self._context

  # get the storegate pointer
  def getStoreGateSvc(self):
    return self._storegateSvc

  # set the storegate from another external source
  def setStoreGateSvc(self, store):
    self._storegateSvc = store


  # number of event
  @property
  def nov(self):
    if self._nov < 0:
      return self.getEntries()
    else:
      return self._nov


