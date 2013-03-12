# -*- coding: utf-8 -*-
import sublime, sublime_plugin
import subprocess, platform, re, os, types
import lessproject

#define methods to convert css, either the current file or all
class Compiler:
  def __init__(self, view):
    self.view = view

  # for command 'LessToCssCommand' and 'AutoLessToCssCommand'
  def convertOne(self, is_auto_save = False):
    fn = self.view.file_name().encode("utf_8")
    if not fn.endswith(".less"):
      return ''

    settings = sublime.load_settings('less2css.sublime-settings')
    base_dir = settings.get("lessBaseDir")
    minimised = settings.get("minify", True)
    auto_compile = settings.get("autoCompile", True)
    main_file = settings.get("main_file", False)
    imports = settings.get("checkImports", False)
    
    #check project for outputDir first
    less_proj = lessproject.LessProject()
    output_dir = less_proj.getProjectLessOutputDir()
    #project output dir explicitly set, so don't try to normalise it
    bypass_project = True

    if output_dir == None:
      output_dir - settings.get("outputDir")
      bypass_project = False

    if auto_compile == False and is_auto_save == True:
      return ''
    
    dirs = self.parseBaseDirs(base_dir, output_dir, bypass_project)
    
    # if you've set the main_file (relative to current file), only that file gets compiled
    # this allows you to have one file with lots of @imports
    if main_file:
      fn = os.path.join(os.path.dirname(fn), main_file)

    if imports:
      return self.convertLessImports(dirs = dirs, file = fn, minimised = minimised)
    
    return self.convertLess2Css(dirs = dirs, file = fn, minimised = minimised)

  # for command 'AllLessToCssCommand'
  def convertAll(self):
    err_count = 0;

    #default_base
    settings = sublime.load_settings('less2css.sublime-settings')
    base_dir = settings.get("lessBaseDir")
    minimised = settings.get("minify", True)

    #check project for outputDir first
    less_proj = lessproject.LessProject()
    output_dir = less_proj.getProjectLessOutputDir()
    #project output dir explicitly set, so don't try to normalise it
    bypass_project = True

    if output_dir == None:
      output_dir - settings.get("outputDir")
      bypass_project = False

    dirs = self.parseBaseDirs(base_dir, output_dir, bypass_project)

    for r,d,f in os.walk(dirs['less']):
      for files in f:
        if files.endswith(".less"):
          #add path to file name
          fn = os.path.join(r, files)
          #call compiler
          resp = self.convertLess2Css(dirs, file = fn, minimised = minimised)

          if resp != "":
            err_count = err_count + 1

    if err_count > 0:
      return "There were errors compiling all LESS files"
    else:
      return ''

  def convertLessImports(self, dirs, file = '', minimised = True):
    if file == "":
      fn = self.view.file_name().encode("utf_8")
    else:
      fn = file

    fn = os.path.split(fn)[1]

    proj_folders = dirs['project']

    if not proj_folders:
      window = sublime.active_window()
      proj_folders = window.folders()

    nodir = self.getExcludedDirs(self.view)

    terms = ['@import "'+fn+'";', '@import-once "'+fn+'";']

    files = []

    for term in terms:
      if isinstance(proj_folders, types.ListType):
        for dir in proj_folders:
          resp = self.doGrep(term, dir, nodir)
      else:
        resp = self.doGrep(term, proj_folders, nodir)

        for f,n in resp:
          print "[less2css] Converting @import container "+f
          files.append(f)

    files.append(fn)
    return self.convertLess2Css(dirs, files, minimised)

  # convert single or subset of files
  def convertLess2Css(self, dirs, file = '', minimised = True):
    out = ''

    #get the current file & its css variant
    if file == "":
      less = self.view.file_name().encode("utf_8")
    else:
      less = file

    if isinstance(less, types.ListType):
      out = ''
      for l in less:
        out += self.doConvertLess2Css(dirs, l, minimised)
      return out
    else:
      return self.doConvertLess2Css(dirs, less, minimised)

  # do convert
  def doConvertLess2Css(self, dirs, less = '', minimised = True):
    if not less.endswith(".less"):
      return ''

    css = re.sub('\.less$', '.css', less)
    sub_path = css.replace(dirs['less'] + os.path.sep, '')
    css = os.path.join(dirs['css'], sub_path)

    # create directories
    output_dir = os.path.dirname(css)
    if not os.path.isdir(output_dir):
      os.makedirs(output_dir)

    if minimised == True:
      cmd = ["lessc", less, css, "-x", "--verbose"]
    else:
      cmd = ["lessc", less, css, "--verbose"]

    print "[less2css] Converting " + less + " to "+ css

    if platform.system() != 'Windows':
      # if is not Windows, modify the PATH
      env = os.getenv('PATH')
      env = env + ':/usr/local/bin:/usr/local/sbin'
      os.environ['PATH'] = env
      if subprocess.call(['which', 'lessc']) == 1:
        return sublime.error_message('less2css error: `lessc` is not avavailable')
    else:
      # change command from lessc to lessc.cmd on Windows,
      # only lessc.cmd works but lessc doesn't
      cmd[0] = 'lessc.cmd'
      
      #different minify flag in less.js-windows
      if minimised == True:
        cmd[3] = '-compress'

    #run compiler
    try:
      p = subprocess.Popen(cmd, stdout = subprocess.PIPE, stderr = subprocess.PIPE) #not sure if node outputs on stderr or stdout so capture both
    except OSError as err:
      return sublime.error_message('less2css error: ' + str(err))
    stdout, stderr = p.communicate()

    #blank lines and control characters
    blank_line_re = re.compile('(^\s+$)|(\033\[[^m]*m)', re.M)

    #decode and replace blank lines
    out = stderr.decode("utf_8")
    out = blank_line_re.sub('', out)

    if out != '':
      print '----[less2cc] Compile Error----'
      print out
    else:
      print '[less2css] Convert completed!'

    return out

  #############
  ### UTILS ###
  #############

  # try to find project folder,
  # and normalize relative paths such as /a/b/c/../d to /a/b/d
  def parseBaseDirs(self, base_dir = './', output_dir = '', bypass_project = False):
    base_dir = './' if base_dir is None else base_dir
    output_dir = '' if output_dir is None else output_dir
    fn = self.view.file_name().encode("utf_8")
    file_dir = os.path.dirname(fn)

    # find project path
    # it seems that there is no shortcuts to get the active project folder,
    # it returns all, so need to find the active one
    proj_dir = ''
    window = sublime.active_window()
    proj_folders = window.folders()
    for folder in proj_folders:
      if fn.startswith(folder):
        proj_dir = folder
        break

    # normalize less base path
    if not base_dir.startswith('/') and bypass_project == False:
      base_dir = os.path.normpath(os.path.join(proj_dir, base_dir))

    # normalize css output base path
    if not output_dir.startswith('/') and bypass_project == False:
      output_dir = os.path.normpath(os.path.join(proj_dir, output_dir))
    
    return { 'project': proj_dir, 'less': base_dir, 'css' : output_dir }

  #search for imports - stolen from my go2function plugin & adapted
  def doGrep(self, word, directory, nodir):
    out = []

    for r,d,f in os.walk(directory):
      if self.canCheckDir(r, nodir):
        for files in f:
          fn = os.path.join(r, files)
          
          search = open(fn, "r")
          lines = search.readlines()
          
          for n, line in enumerate(lines):
            if word in line:
              out.append((fn, n))

          search.close()
            
    return out

  #which dirs don't we want to search?
  def getExcludedDirs(self, view):
    #this gets the folder_exclude_patterns from the settings file, not the project file
    dirs = view.settings().get("folder_exclude_patterns", [".git", ".svn", "CVS", ".hg"]) #some defaults
    return dirs

  #can we look inside this directory?
  def canCheckDir(self, dir, excludes):
    count = 0

    #potentially quite expensive - better way?
    for no in excludes:
      if no not in dir:
        count = count + 1

    if count == len(excludes):
      return True
    else:
      return False
