


local bAssertByCiv = false
	--setting to "false" makes the code use the leader instead of the civ
local sDesiredCivName = "CIVILIZATION_LEU_ARGENTINA"
local sDesiredLeaderName = "LEADER_LEU_ROCA"
local traitMod = "TRAIT_LEADER_LEU_ROCA"


--================================================================================================================
-- functions specific to the desired effect

-- VictoriousPlayerFunction() is called from the actual function directly-hooked to Events.UnitKilledInCombat
-- to create a different effect just change the code in VictoriousPlayerFunction()
--	or create a different function-name with its own set of passed arguments
--	or just replace the line in function OnUnitKilledInCombat: VictoriousPlayerFunction(Map.GetPlot(iActionX, iActionY), pVictoriousUnit, iVictoriousPlayer, bVictoriousUnitIsRanged)
--		with whatever code is needed to create the desired effect
--================================================================================================================

local tTableOfImprovements = {[GameInfo.Improvements["IMPROVEMENT_PASTURE"].Index]="true", [GameInfo.Improvements["IMPROVEMENT_FORT"].Index]="true"}

function CloseCityGetter(iPlayer, pPlot)
	print("GettingCloseCity")
	iCityRadius = 3
	for dx = (iCityRadius * -1), iCityRadius do
		for dy = (iCityRadius * -1), iCityRadius do
			local cPlot = Map.GetPlotXYWithRangeCheck(pPlot:GetX(), pPlot:GetY(), dx, dy, iCityRadius);
			print("Checking a Plot")
			if cPlot == nil then print("Plot is NIL") end
			if cPlot ~= nil then 
				print("Plot is not NIL")
				if cPlot:GetDistrictType() == GameInfo.Districts["DISTRICT_CITY_CENTER"].Index then
					print("Found a City Plot!")
					if cPlot:GetOwner() == iPlayer then
						print("The owner is qt")
						return Cities.GetCityInPlot(cPlot:GetX(), cPlot:GetY());
					end
				end
			end
		end
	end
	print("No Close City Found")
	return nil
end

function SetAdjacentPlotsOwner(iPlayer, pPlot, bMustNotBeOwned, bIncludeCenterPlot)
	if bIncludeCenterPlot then
		if (iPlayer ~= pPlot:GetOwner()) then
			if bMustNotBeOwned then
				if (pPlot:GetOwner() == -1) then
					pPlot:SetOwner(iPlayer)
					iCity = CloseCityGetter(iPlayer, pPlot)
					if iCity ~= nil then
						WorldBuilder.CityManager():SetPlotOwner(pPlot, iCity)
					end
				end
			else
				pPlot:SetOwner(iPlayer)
				iCity = CloseCityGetter(iPlayer, pPlot)
				if iCity ~= nil then
					WorldBuilder.CityManager():SetPlotOwner(pPlot, iCity)
				end
			end
		end
	end
	for direction = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1, 1 do
		local adjacentPlot = Map.GetAdjacentPlot(pPlot:GetX(), pPlot:GetY(), direction);
		if adjacentPlot then
			if (iPlayer ~= adjacentPlot:GetOwner()) then
				if bMustNotBeOwned then
					if (adjacentPlot:GetOwner() == -1) then
						adjacentPlot:SetOwner(iPlayer)
						iCity = CloseCityGetter(iPlayer, adjacentPlot)
						if iCity ~= nil then
							WorldBuilder.CityManager():SetPlotOwner(adjacentPlot, iCity)
						end
					end
				else
					if adjacentPlot:GetDistrictType() == GameInfo.Districts["DISTRICT_CITY_CENTER"].Index then
						print("The plot is a city!!")
					else
						adjacentPlot:SetOwner(iPlayer)
						iCity = CloseCityGetter(iPlayer, adjacentPlot)
						if iCity ~= nil then
							WorldBuilder.CityManager():SetPlotOwner(adjacentPlot, iCity)
						end
					end
				end
			end
		end
	end
end
function PlotIsAdjacentToReqImprovement(pPlot, tTable, iPlayer)
	for direction = 0, DirectionTypes.NUM_DIRECTION_TYPES - 1, 1 do
		local adjacentPlot = Map.GetAdjacentPlot(pPlot:GetX(), pPlot:GetY(), direction);
		if adjacentPlot then
			if tTable[adjacentPlot:GetImprovementType()] and (adjacentPlot:GetOwner() == iPlayer) then
				return adjacentPlot
			end
		end
	end
	return nil
end
function VictoriousPlayerFunction(pPlot)
	--When an enemy unit is defeated next to an owned Fort or a Pasture it grants you all adjacent tiles.
	--if bUnitIsRanged then
	--	print("[VictoriousPlayerFunction]: bUnitIsRanged == true")
	--	if tTableOfImprovements[pPlot:GetImprovementType()] and (pPlot:GetOwner() == iPlayer) then
	--		print("[VictoriousPlayerFunction]: The ranged unit is on a plot owned by the victorious player that also has a correct improvement")
	--		SetAdjacentPlotsOwner(iPlayer, pPlot, true, false)
	--	else
	--		print("[VictoriousPlayerFunction]: bUnitIsRanged == true: no plots were grabbed for the player")
	--	end
	--else
		iPlayer = 90
		for iLoopPlayer = 0, 62 do
			local pLoopPlayer = Players[iLoopPlayer]
			if pLoopPlayer:IsAlive() then
				if (PlayerConfigurations[iLoopPlayer]:GetLeaderTypeName() == sDesiredLeaderName) then
					iPlayer = iLoopPlayer
				end
			end
		end
		print (iPlayer)
		local pImprovementPlot = PlotIsAdjacentToReqImprovement(pPlot, tTableOfImprovements, iPlayer)
		pPlotCheck = false
		if tTableOfImprovements[pPlot:GetImprovementType()] and pPlot:GetOwner() == iPlayer then pPlotCheck = true end
		if pPlotCheck == true or pImprovementPlot ~= nil then
			SetAdjacentPlotsOwner(iPlayer, pPlot, false, true)
		else
			print("[VictoriousPlayerFunction]: no adjacent plot had a Pasture or Fort that was owned by the victorious player")
			print("[VictoriousPlayerFunction]: no plots were grabbed for the player")
		end
	--end
end
--=======================================================================================================
-- Generic Functions to Track Unit-Killing via combat.
-- You do not normally want to remove these
-- You should also generally only make alterations to function OnUnitKilledInCombat()
--=======================================================================================================

function LeaderOrCivIsInPlay(bCheckByCiv, sRequiredCivName, sRequiredLeaderName)
	local bPlayerIsActive, tFoundValidPlayers = false, {}
	for iLoopPlayer = 0, 62 do
		local pLoopPlayer = Players[iLoopPlayer]
		if pLoopPlayer:IsAlive() then
			if bCheckByCiv then
				if (PlayerConfigurations[iLoopPlayer]:GetCivilizationTypeName() == sRequiredCivName) then
					bPlayerIsActive = true
					tFoundValidPlayers[iLoopPlayer] = PlayerConfigurations[iLoopPlayer]:GetLeaderTypeName()
				end
			else
				if (PlayerConfigurations[iLoopPlayer]:GetLeaderTypeName() == sRequiredLeaderName) then
					bPlayerIsActive = true
					tFoundValidPlayers[iLoopPlayer] = PlayerConfigurations[iLoopPlayer]:GetLeaderTypeName()
				end
			end
		end
	end
	return bPlayerIsActive, tFoundValidPlayers
end
local bLeaderOrCivIsInPlay, tValidPlayers = LeaderOrCivIsInPlay(bAssertByCiv, sDesiredCivName, sDesiredLeaderName)

function UnitIsDeadToPlayer(pUnit, iPlayer)
	if pUnit then
		if (pUnit:GetX() == nil) or (pUnit:GetX() < 0) or (pUnit:GetY() == nil) or (pUnit:GetY() < 0) or (pUnit:GetOwner() ~= iPlayer) then
			return true
		end
	else
		--the pUnit data is nil, assume the unit is ded
		return true
	end
	--safety valve point: assume the unit is not ded if we get here
	return false
end
-----------------------------------
-- Leugi addendums-----------------
-----------------------------------
local UnitPositionXTable = {}
local UnitPositionYTable = {}

function UnitSaver(PlayerID, UnitID)
	--print(UnitID)
	local pPlayer = Players[PlayerID]
	local pUnit = ((pPlayer:GetUnits():FindID(UnitID) == nil) and -1 or pPlayer:GetUnits():FindID(UnitID))
	iX, iY = pUnit:GetX(), pUnit:GetY()
	--print("X: " .. iX .. "")
	--print("Y: " .. iY .. "")
	if iX < 0 then return false end
	UnitPositionXTable[UnitID] = iX
	UnitPositionYTable[UnitID] = iY
end

function OnMoveUnitSaver(PlayerID, UnitID, x, y)
	--print("SavingUnitPosition on Move")
	UnitSaver(PlayerID, UnitID)
end

function OnDamageUnitSaver(PlayerID, UnitID, newDamage, prevDamage)
	--print("SavingUnitPosition on Damage")
	UnitSaver(PlayerID, UnitID)
end

function OnUnitAddedtoMapSaver(PlayerID, UnitID)
	--print("SavingUnitPosition on Map")
	UnitSaver(PlayerID, UnitID)
end

-------------------------------------
function OnUnitDamaged(iDefeatedPlayer, iDefeatedUnitID, newDamage, prevDamage)
	local pDefeatedPlayer = Players[iDefeatedPlayer]
	local bDefeatedUnitIsDead = UnitIsDeadToPlayer(pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID), iDefeatedPlayer)
	if bDefeatedUnitIsDead then
		print("[OnUnitDamaged]: iDefeatedPlayer = " .. iDefeatedPlayer .. ", iDefeatedUnitID = " .. iDefeatedUnitID .. "")
		local iActionX, iActionY, tDefeatedUnitData, tVictoriousUnitData, bVictoriousUnitIsRanged = -1, -1, -1, -1, false
		local pDefeatedUnit = ((pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID) == nil) and -1 or pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID))
		iActionX, iActionY = UnitPositionXTable[iDefeatedUnitID], UnitPositionYTable[iDefeatedUnitID]
		print("[OnUnitDamaged]: Action Plot is determined via the defeated unit as iActionX = " .. iActionX .. ", iActionY = " .. iActionY)
		VictoriousPlayerFunction(Map.GetPlot(iActionX, iActionY))
	end
end

function OnUnitKilledInCombat(iDefeatedPlayer, iDefeatedUnitID, iVictoriousPlayer, iVictoriousUnitID)
	--if pVictoriousPlayer:IsTurnActive() then
	--local pSelectedUnit = UI.GetHeadSelectedUnit()
	if tValidPlayers[iVictoriousPlayer] then
		print("[OnUnitKilledInCombat]: iDefeatedPlayer = " .. iDefeatedPlayer .. ", iDefeatedUnitID = " .. iDefeatedUnitID .. ", iVictoriousPlayer = " .. iVictoriousPlayer .. ", iVictoriousUnitID = " .. iVictoriousUnitID)
		local pDefeatedPlayer = Players[iDefeatedPlayer]
		local pVictoriousPlayer = Players[iVictoriousPlayer]
		local bDefeatedUnitIsDead = UnitIsDeadToPlayer(pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID), iDefeatedPlayer)
		local bVictoriousUnitIsDead = UnitIsDeadToPlayer(pVictoriousPlayer:GetUnits():FindID(iVictoriousUnitID), iVictoriousPlayer)
		--if bDefeatedUnitIsDead and bVictoriousUnitIsDead then
			--both units are dead or nil, do nothing
		--	print("[OnUnitKilledInCombat]: both units are dead or nil --> terminating")
		--	return
		--end
		local iActionX, iActionY, tDefeatedUnitData, tVictoriousUnitData, bVictoriousUnitIsRanged = -1, -1, -1, -1, false
		local pDefeatedUnit = ((pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID) == nil) and -1 or pDefeatedPlayer:GetUnits():FindID(iDefeatedUnitID))
		local pVictoriousUnit = ((pVictoriousPlayer:GetUnits():FindID(iVictoriousUnitID) == nil) and -1 or pVictoriousPlayer:GetUnits():FindID(iVictoriousUnitID))
		local bCanVerifyDefeatedUnitPosition = true
		local bDefeatedUnitIsAlive = not bDefeatedUnitIsDead
		local bVictoriousUnitIsAlive = not bVictoriousUnitIsDead
		if bDefeatedUnitIsAlive and bVictoriousUnitIsAlive then
			--both units are "alive" when the event fires, eesh
			print("[OnUnitKilledInCombat]: both units are 'alive' --> terminating")
			return
		end
		if (pDefeatedUnit ~= -1) then
			--bCanVerifyDefeatedUnitPosition = (pDefeatedUnit:GetX() ~= nil) and (pDefeatedUnit:GetX() >= 0) and (pDefeatedUnit:GetY() ~= nil) and (pDefeatedUnit:GetY() >= 0)
			--if (pDefeatedUnit:GetType() ~= nil) and (GameInfo.Units[pDefeatedUnit:GetType()] ~= nil) then
			--	tDefeatedUnitData = GameInfo.Units[pDefeatedUnit:GetType()]
			--end
			--print("So... the Defeated unit is not -1, we should be able to get the position, right? right?")
			
		--	print("The x is " .. UnitPositionXTable[iDefeatedUnitID] .. "")
			--print("The y is " .. UnitPositionYTable[iDefeatedUnitID] .. "")
			
			--print("Sorry LeeS to butcher your code ;-;")
		end
		if (pVictoriousUnit ~= -1) then
			if (pVictoriousUnit:GetType() ~= nil) and (GameInfo.Units[pVictoriousUnit:GetType()] ~= nil) then
				tVictoriousUnitData = GameInfo.Units[pVictoriousUnit:GetType()]
			end
			bVictoriousUnitIsRanged = (tVictoriousUnitData.Range > 0)
		end
		if bCanVerifyDefeatedUnitPosition then
			iActionX, iActionY = UnitPositionXTable[iDefeatedUnitID], UnitPositionYTable[iDefeatedUnitID]
			print("[OnUnitKilledInCombat]: Action Plot is determined via the defeated unit as iActionX = " .. iActionX .. ", iActionY = " .. iActionY)
		else
			if (pVictoriousUnit ~= -1) then
				if pVictoriousPlayer:IsTurnActive() then
					--Victorious Unit Attacked
					if (bVictoriousUnitIsRanged == false) then
						--Victorious Unit is a melee attack unit: Use the Defending Unit's XY
						iActionX, iActionY = pVictoriousUnit:GetX(), pVictoriousUnit:GetY()
						print("[OnUnitKilledInCombat]: Action Plot is determined via the victorious unit as iActionX = " .. iActionX .. ", iActionY = " .. iActionY)
					else
						print("[OnUnitKilledInCombat]: The Victorious unit is ranged, more code gymnastics are required")
						if tVictoriousUnitData.Domain == "DOMAIN_LAND" then
							print("[OnUnitKilledInCombat]: Attack was by land ranged unit:  --> using the ranged unit's plot")
							iActionX, iActionY = pVictoriousUnit:GetX(), pVictoriousUnit:GetY()
						elseif tVictoriousUnitData.Domain == "DOMAIN_SEA" then
							print("[OnUnitKilledInCombat]: Attack was by sea ranged unit:  --> terminating")
							return
						elseif tVictoriousUnitData.Domain == "DOMAIN_AIR" then
							print("[OnUnitKilledInCombat]: Attack was by air ranged unit:  --> terminating")
							return
						end
					end
				else
					--Victorious Unit Defended: Use the Defending Unit's XY
					iActionX, iActionY = pVictoriousUnit:GetX(), pVictoriousUnit:GetY()
				end
			else
				print("[OnUnitKilledInCombat]: Action Plot cannot be determined:  --> terminating")
				return
			end
		end
		--only way we can get here is by determining a valid iActionX, iActionY
		VictoriousPlayerFunction(Map.GetPlot(iActionX, iActionY), pVictoriousUnit, iVictoriousPlayer, bVictoriousUnitIsRanged)
	end
end
if bLeaderOrCivIsInPlay then
	--Events.UnitKilledInCombat.Add(OnUnitKilledInCombat)
	Events.UnitDamageChanged.Add(OnUnitDamaged)
	Events.UnitMoved.Add(OnMoveUnitSaver)
	--Events.UnitDamageChanged.Add(OnDamageUnitSaver)
	Events.UnitAddedToMap.Add(OnUnitAddedtoMapSaver)
	if bAssertByCiv then
		print(sDesiredCivName .. " is active in the game: Events.UnitKilledInCombat.Add(OnUnitKilledInCombat) activated")
	else
		print(sDesiredLeaderName .. " is active in the game: Events.UnitKilledInCombat.Add(OnUnitKilledInCombat) activated")
	end
else
	print("Neither " .. sDesiredCivName .. " or " .. sDesiredLeaderName .. " is active in the game: no game events activated")
end
