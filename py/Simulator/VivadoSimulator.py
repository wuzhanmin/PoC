# EMACS settings: -*-	tab-width: 2; indent-tabs-mode: t; python-indent-offset: 2 -*-
# vim: tabstop=2:shiftwidth=2:noexpandtab
# kate: tab-width 2; replace-tabs off; indent-width 2;
# 
# ==============================================================================
# Authors:				 	Patrick Lehmann
# 
# Python Class:			TODO
# 
# Description:
# ------------------------------------
#		TODO:
#		- 
#		- 
#
# License:
# ==============================================================================
# Copyright 2007-2016 Technische Universitaet Dresden - Germany
#											Chair for VLSI-Design, Diagnostics and Architecture
# 
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#		http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
#
# entry point
if __name__ != "__main__":
	# place library initialization code here
	pass
else:
	from lib.Functions import Exit
	Exit.printThisIsNoExecutableFile("The PoC-Library - Python Module Simulator.VivadoSimulator")

# load dependencies
from configparser							import NoSectionError
from os												import chdir

from colorama									import Fore as Foreground

from Base.Exceptions					import SimulatorException
from Base.Project							import FileTypes, VHDLVersion, Environment, ToolChain, Tool, FileListFile
from Base.Simulator						import Simulator as BaseSimulator#, VHDLTestbenchLibraryName
from Parser.Parser						import ParserException
from PoC.PoCProject						import Project as PoCProject
from ToolChains.Xilinx.Vivado	import Vivado


# Workaround for Vivado 2015.4
VHDLTestbenchLibraryName = "work"

class Simulator(BaseSimulator):
	__guiMode =					False

	def __init__(self, host, showLogs, showReport, guiMode):
		super(self.__class__, self).__init__(host, showLogs, showReport)

		self._guiMode =				guiMode
		self._vivado =				None

		self._LogNormal("preparing simulation environment...")
		self._PrepareSimulationEnvironment()

	@property
	def TemporaryPath(self):
		return self._tempPath

	def _PrepareSimulationEnvironment(self):
		self._LogNormal("  preparing simulation environment...")
		
		# create temporary directory for ghdl if not existent
		self._tempPath = self.Host.Directories["xSimTemp"]
		if (not (self._tempPath).exists()):
			self._LogVerbose("  Creating temporary directory for simulator files.")
			self._LogDebug("    Temporary directors: {0}".format(str(self._tempPath)))
			self._tempPath.mkdir(parents=True)
			
		# change working directory to temporary xSim path
		self._LogVerbose("  Changing working directory to temporary directory.")
		self._LogDebug("    cd \"{0}\"".format(str(self._tempPath)))
		chdir(str(self._tempPath))

	def PrepareSimulator(self, binaryPath, version):
		# create the GHDL executable factory
		self._LogVerbose("  Preparing GHDL simulator.")
		self._vivado = Vivado(self.Host.Platform, binaryPath, version, logger=self.Logger)

	def RunAll(self, pocEntities, **kwargs):
		for pocEntity in pocEntities:
			self.Run(pocEntity, **kwargs)
		
	def Run(self, entity, board, vhdlVersion="93", vhdlGenerics=None):
		self._entity =				entity
		self._testbenchFQN =	str(entity)										# TODO: implement FQN method on PoCEntity
		self._vhdlVersion =		vhdlVersion
		self._vhdlGenerics =	vhdlGenerics

		# check testbench database for the given testbench		
		self._LogQuiet("Testbench: {0}{1}{2}".format(Foreground.YELLOW, self._testbenchFQN, Foreground.RESET))
		if (not self.Host.TBConfig.has_section(self._testbenchFQN)):
			raise SimulatorException("Testbench '{0}' not found.".format(self._testbenchFQN)) from NoSectionError(self._testbenchFQN)
			
		# setup all needed paths to execute fuse
		testbenchName =				self.Host.TBConfig[self._testbenchFQN]['TestbenchModule']
		fileListFilePath =		self.Host.Directories["PoCRoot"] / self.Host.TBConfig[self._testbenchFQN]['fileListFile']

		self._CreatePoCProject(testbenchName, board)
		self._AddFileListFile(fileListFilePath)
		
		# self._RunCompile(testbenchName)
		self._RunLink(testbenchName)
		self._RunSimulation(testbenchName)
		
	def _CreatePoCProject(self, testbenchName, board):
		# create a PoCProject and read all needed files
		self._LogDebug("    Create a PoC project '{0}'".format(str(testbenchName)))
		pocProject =									PoCProject(testbenchName)
		
		# configure the project
		pocProject.RootDirectory =		self.Host.Directories["PoCRoot"]
		pocProject.Environment =			Environment.Simulation
		pocProject.ToolChain =				ToolChain.Xilinx_Vivado
		pocProject.Tool =							Tool.Xilinx_xSim
		pocProject.VHDLVersion =			self._vhdlVersion
		pocProject.Board =						board

		self._pocProject =						pocProject
		
	def _AddFileListFile(self, fileListFilePath):
		self._LogDebug("    Reading filelist '{0}'".format(str(fileListFilePath)))
		# add the *.files file, parse and evaluate it
		try:
			fileListFile = self._pocProject.AddFile(FileListFile(fileListFilePath))
			fileListFile.Parse()
			fileListFile.CopyFilesToFileSet()
			fileListFile.CopyExternalLibraries()
			self._pocProject.ExtractVHDLLibrariesFromVHDLSourceFiles()
		except ParserException as ex:										raise SimulatorException("Error while parsing '{0}'.".format(str(fileListFilePath))) from ex
		
		self._LogDebug(self._pocProject.pprint(2))
		self._LogDebug("=" * 160)
		if (len(fileListFile.Warnings) > 0):
			for warn in fileListFile.Warnings:
				self._LogWarning(warn)
			raise SimulatorException("Found critical warnings while parsing '{0}'".format(str(fileListFilePath)))
		
	def _RunCompile(self, testbenchName):
		self._LogNormal("  compiling source files...")
		
		# create one VHDL line for each VHDL file
		xSimProjectFileContent = ""
		for file in self._pocProject.Files(fileType=FileTypes.VHDLSourceFile):
			if (not file.Path.exists()):									raise SimulatorException("Can not add '{0}' to xSim project file.".format(str(file.Path))) from FileNotFoundError(str(file.Path))
			xSimProjectFileContent += "vhdl {0} \"{1}\"\n".format(file.VHDLLibraryName, str(file.Path))
						
		# write xSim project file
		prjFilePath = self._tempPath / (testbenchName + ".prj")
		self._LogDebug("Writing xSim project file to '{0}'".format(str(prjFilePath)))
		with prjFilePath.open('w') as prjFileHandle:
			prjFileHandle.write(xSimProjectFileContent)
		
		# create a VivadoVHDLCompiler instance
		xvhcomp = self._vivado.GetVHDLCompiler()
		xvhcomp.Compile(str(prjFilePath))
		
	def _RunLink(self, testbenchName):
		self._LogNormal("  running xelab...")
		
		xelabLogFilePath =	self._tempPath / (testbenchName + ".xelab.log")
	
		# create one VHDL line for each VHDL file
		xSimProjectFileContent = ""
		vhdlFiles = [item for item in self._pocProject.Files(fileType=FileTypes.VHDLSourceFile)]
		for file in vhdlFiles[:-1]:
			if (not file.Path.exists()):									raise SimulatorException("Can not add '{0}' to xSim project file.".format(str(file.Path))) from FileNotFoundError(str(file.Path))
			if (self._vhdlVersion == VHDLVersion.VHDL2008):
				xSimProjectFileContent += "vhdl2008 {0} \"{1}\"\n".format(file.VHDLLibraryName, str(file.Path))
			else:
				xSimProjectFileContent += "vhdl {0} \"{1}\"\n".format(file.VHDLLibraryName, str(file.Path))

		# Workaround for Vivado 2015.4: last VHDL file is testbench, rewrite library name
		file = vhdlFiles[-1]
		if (not file.Path.exists()):									raise SimulatorException("Can not add '{0}' to xSim project file.".format(str(file.Path))) from FileNotFoundError(str(file.Path))
		if (self._vhdlVersion == VHDLVersion.VHDL2008):
			xSimProjectFileContent += "vhdl2008 {0} \"{1}\"\n".format(VHDLTestbenchLibraryName, str(file.Path))
		else:
			xSimProjectFileContent += "vhdl {0} \"{1}\"\n".format(VHDLTestbenchLibraryName, str(file.Path))

		# write xSim project file
		prjFilePath = self._tempPath / (testbenchName + ".prj")
		self._LogDebug("Writing xSim project file to '{0}'".format(str(prjFilePath)))
		with prjFilePath.open('w') as prjFileHandle:
			prjFileHandle.write(xSimProjectFileContent)
	
		# create a VivadoLinker instance
		xelab = self._vivado.GetElaborator()
		xelab.Parameters[xelab.SwitchTimeResolution] =	"1fs"	# set minimum time precision to 1 fs
		xelab.Parameters[xelab.SwitchMultiThreading] =	"off"	#"4"		# enable multithreading support
		xelab.Parameters[xelab.FlagRangeCheck] =				True

		# xelab.Parameters[xelab.SwitchOptimization] =		"2"
		xelab.Parameters[xelab.SwitchDebug] =						"typical"
		xelab.Parameters[xelab.SwitchSnapshot] =				testbenchName

		# if (self._vhdlVersion == VHDLVersion.VHDL2008):
		# 	xelab.Parameters[xelab.SwitchVHDL2008] =			True

		# if (self.verbose):
		xelab.Parameters[xelab.SwitchVerbose] =					"1"	#"0"
		xelab.Parameters[xelab.SwitchProjectFile] =			str(prjFilePath)
		xelab.Parameters[xelab.SwitchLogFile] =					str(xelabLogFilePath)
		xelab.Parameters[xelab.ArgTopLevel] =						"{0}.{1}".format(VHDLTestbenchLibraryName, testbenchName)
		xelab.Link()

	def _RunSimulation(self, testbenchName):
		self._LogNormal("  running simulation...")
		
		xSimLogFilePath =		self._tempPath / (testbenchName + ".xSim.log")
		tclBatchFilePath =	self.Host.Directories["PoCRoot"] / self.Host.TBConfig[self._testbenchFQN]['xSimBatchScript']
		tclGUIFilePath =		self.Host.Directories["PoCRoot"] / self.Host.TBConfig[self._testbenchFQN]['xSimGUIScript']
		wcfgFilePath =			self.Host.Directories["PoCRoot"] / self.Host.TBConfig[self._testbenchFQN]['xSimWaveformConfigFile']

		# create a VivadoSimulator instance
		xSim = self._vivado.GetSimulator()
		xSim.Parameters[xSim.SwitchLogFile] =					str(xSimLogFilePath)

		if (not self._guiMode):
			xSim.Parameters[xSim.SwitchTclBatchFile] =	str(tclBatchFilePath)
		else:
			xSim.Parameters[xSim.SwitchTclBatchFile] =	str(tclGUIFilePath)
			xSim.Parameters[xSim.FlagGuiMode] =					True

			# if xSim save file exists, load it's settings
			if wcfgFilePath.exists():
				self._LogDebug("    Found waveform config file: '{0}'".format(str(wcfgFilePath)))
				xSim.Parameters[xSim.SwitchWaveformFile] =	str(wcfgFilePath)
			else:
				self._LogDebug("    Didn't find waveform config file: '{0}'".format(str(wcfgFilePath)))

		xSim.Parameters[xSim.SwitchSnapshot] = "{0}.{1}#{0}.{1}".format(VHDLTestbenchLibraryName, testbenchName)
		xSim.Simulate()

		# print()
		# if (not self.__guiMode):
			# try:
				# result = self.checkSimulatorOutput(simulatorLog)
				
				# if (result == True):
					# print("Testbench '%s': PASSED" % testbenchName)
				# else:
					# print("Testbench '%s': FAILED" % testbenchName)
					
			# except SimulatorException as ex:
				# raise TestbenchException("PoC.ns.module", testbenchName, "'SIMULATION RESULT = [PASSED|FAILED]' not found in simulator output.") from ex
	
