-- -----------------------------------------------
-- -- TAINO SCRIPTS
-- -----------------------------------------------

-- -----------------------------------------------
-- -- UTILITIES
-- -----------------------------------------------

-- function C15_ValidTrait(sTrait) -- Chrisy
--     local tValid = {}
--     for k, v in ipairs(PlayerManager.GetWasEverAliveIDs()) do
--         local leaderType = PlayerConfigurations[v]:GetLeaderTypeName()
--         for trait in GameInfo.LeaderTraits() do
--             if trait.LeaderType == leaderType and trait.TraitType == sTrait then 
--                 tValid[v] = true 
--             end;
--         end
--         if not tValid[v] then
--             local civType = PlayerConfigurations[v]:GetCivilizationTypeName()
--             for trait in GameInfo.CivilizationTraits() do
--                 if trait.CivilizationType == civType and trait.TraitType == sTrait then 
--                     tValid[v] = true 
--                 end;
--             end
--         end
--     end
--     return tValid
-- end

-- -----------------------------------------------
-- -- CONSTANTS
-- -----------------------------------------------

-- 	local sTrait = "TRAIT_CIVILIZATION_CVS_TAINO_UA"
-- 	local tTraitPlayers = C15_ValidTrait(sTrait)
-- 	local iDummy = GameInfo.Buildings["BUILDING_CVS_TAINO_UP_DUMMY"].Index;
-- 	local sProject = "PROJECT_CVS_TAINO_UP"

-- -----------------------------------------------
-- -- FUNCTION CPG_TainoDummy
-- -- Credits: ChimpanG
-- -----------------------------------------------

-- function CPG_TainoDummy(playerID, cityID, objectGroupID, objectID, bCancelled)
	
-- 	if tTraitPlayers[playerID] then -- Check player trait
-- 		local pPlayer = Players[playerID]
-- 		local pCities = pPlayer:GetCities()
-- 		local pCity = pCities:FindID(cityID)

-- 		if pCity then
-- 			local pCityBuildings = pCity:GetBuildings() -- Get city buildings
-- 			local pQueue = pCity:GetBuildQueue():CurrentlyBuilding() -- Get build queue
-- 			if pQueue == sProject then -- if the city is building the project then...

-- 				-- add dummy building to city
-- 				if pCityBuildings:HasBuilding(iDummy) ~= true then
-- 					local pPlot = Map.GetPlot(pCity:GetX(), pCity:GetY())
-- 					local iPlot = pPlot:GetIndex()
-- 					pCity:GetBuildQueue():CreateIncompleteBuilding(iDummy, iPlot, 100)
-- 				end
-- 			else -- if not then...
-- 				-- remove dummy from city
-- 				if pCityBuildings:HasBuilding(iDummy) then
-- 					pCityBuildings:RemoveBuilding(iDummy)
-- 				end
-- 			end
-- 		end
-- 	end
-- end
				
-- Events.CityProductionChanged.Add(CPG_TainoDummy);